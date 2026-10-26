"""The jobs of the FastAPI app: a worker process runs them (ADR 0029).

Each job gets the module `app/jobs/<job>.py`: its schedule or its time,
the filter of its records, and the call of its operation. A job without
an entity calls the function of its extension file `app/jobs/<job>_ext.py`
(a generation gap). `app/core/jobs.py` keeps the runs in the table
`job_runs`, so that two workers never start the same run, and
`app/worker.py` runs all jobs in a loop.
"""

import datetime as dt
import textwrap
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import JsonValue

from appgen.bindings.fastapi.dashboards import FilterBuilder, FilterValues
from appgen.bindings.fastapi.integrations import python_apis
from appgen.bindings.fastapi.pysource import LINE_LENGTH, call, from_import, import_block, string
from appgen.bindings.fastapi.queries import Call, Expr, render
from appgen.dsl.cron import Cron, parse_cron
from appgen.dsl.jobs import OFFSET_UNITS, parse_offset
from appgen.dsl.model import AppDefinition
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyField, PyOperation

TABLE = "job_runs"
"""The table of the runs of the jobs. The Next.js app has the same table."""
TEST_TIME = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC)
"""The time of the records of the generated tests: the value of the field of `at`."""
TEST_START = dt.datetime(2026, 6, 15, 0, 0, tzinfo=dt.UTC)
"""The generated tests of a job with a schedule run at the first times after this time."""
_MODULES = frozenset({"__init__"})
"""The names that a job cannot have: the modules of `app/jobs/`."""


@dataclass(slots=True)
class PySchedule:
    """The cron schedule of a job, in UTC."""

    cron: Cron

    @property
    def expression(self) -> str:
        return self.cron.expression

    def code(self) -> str:
        """Return the `Schedule(...)` construction of `app/core/jobs.py`, in the format of Ruff."""
        sets = (
            ("minutes", self.cron.minutes, 0, 59),
            ("hours", self.cron.hours, 0, 23),
            ("days", self.cron.days, 1, 31),
            ("months", self.cron.months, 1, 12),
            ("weekdays", self.cron.weekdays, 0, 6),
        )
        args = [string(self.expression), *(f"{n}={_set(v, lo, hi)}" for n, v, lo, hi in sets)]
        if self.cron.either_day:
            args.append("either_day=True")
        return call("SCHEDULE = ", "jobs.Schedule", args, 0)

    def times(self) -> tuple[dt.datetime, dt.datetime]:
        """Return the first two times of the schedule after `TEST_START`, for the tests."""
        first = self.cron.next_after(TEST_START)
        second = self.cron.next_after(first) if first is not None else None
        if first is None or second is None:
            raise GenerationError(
                f"The schedule '{self.expression}' has no two times in the year after "
                f"{TEST_START:%Y-%m-%d}, so that the tests cannot run the job."
            )
        return first, second

    def test_codes(self) -> tuple[str, str]:
        """Return the first two times of the schedule after `TEST_START` as Python code."""
        first, second = self.times()
        return _datetime_code(first), _datetime_code(second)


@dataclass(slots=True)
class PyJobTest:
    """The values of the filter fields of the records of the generated tests of a job."""

    passing: dict[str, str]
    """The attributes and the Python values of a record that passes the filter."""
    failing: tuple[str, str] | None
    """The attribute and the Python value of a record that fails the filter, or None."""
    now: bool = False
    """True if the values use `now`, the time of the run of the test."""


@dataclass(frozen=True, slots=True)
class PyJobClient:
    """A client of an API that the operation of a job calls: the worker creates it."""

    param: str
    """The variable of the client, and the parameter of the operation."""
    client: str
    """The class of the client, or the function that gives a client with the token of a user."""
    args: list[str]
    """The arguments of the client from the settings."""
    module: str
    """The package of the API in `app/integrations/`."""
    api: str = ""
    """The name of the API in the definition."""
    user: str | None = None
    """The authorization code flow: the expression of the ID of the user, for example
    `record.owner_id` (ADR 0033)."""


@dataclass(slots=True)
class PyJobFilter:
    """The filter of a job with an entity: the joins and the conditions of its records."""

    id: str
    entity: PyEntity
    joins: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    where: list[Expr] = field(default_factory=list[Expr])
    today: bool = False
    now: bool = False


@dataclass(slots=True)
class PyJob:
    """A job: the worker runs its operation, or its extension function, at its times."""

    name: str
    id: str
    description: str | None
    entity: PyEntity | None = None
    operation: PyOperation | None = None
    at: PyField | None = None
    """The field of the time of a record, for a job with `at`."""
    offset: str = "0m"
    """The offset of `at`, as the definition gives it, for example `-24h`."""
    schedule: PySchedule | None = None
    filter: PyJobFilter | None = None
    test: PyJobTest | None = None
    clients: list[PyJobClient] = field(default_factory=list["PyJobClient"])
    """The clients of the APIs that the operation calls."""

    @property
    def module(self) -> str:
        return self.name

    @property
    def gap(self) -> bool:
        """True for a job without an entity: its extension file has the logic."""
        return self.entity is None

    @property
    def offset_code(self) -> str:
        """The offset as a Python expression, for example `dt.timedelta(hours=-24)`."""
        delta = parse_offset(self.offset)
        if not delta:
            return "dt.timedelta()"
        unit = OFFSET_UNITS[self.offset[-1]]
        return f"dt.timedelta({unit}={int(self.offset[:-1])})"

    def docstring(self) -> str:
        """Return the paragraph of the module docstring that tells when the job runs, and what."""
        if self.schedule is not None:
            text = f"The job runs on the schedule `{self.schedule.expression}` (UTC)."
        else:
            assert self.at is not None
            offset = f" with the offset `{self.offset}`" if parse_offset(self.offset) else ""
            text = f"The job runs for each record at the time of `{self.at.name}`{offset}."
        if self.operation is not None and self.entity is not None:
            text += (
                f" Each run calls the operation `{self.operation.name}` on a"
                f" {self.entity.name} record that the filter of the job selects."
            )
        else:
            text += (
                f" Each run calls the function of `{self.module}_ext.py`, which appgen"
                " creates once and never changes."
            )
        text += " `app/worker.py` runs the job."
        return textwrap.fill(text, 72, break_long_words=False, break_on_hyphens=False)

    @property
    def fixed_filter(self) -> bool:
        """True if the filter does not use the time of the pass (`$now` or `$today`)."""
        return self.filter is None or not (self.filter.today or self.filter.now)

    def where_lines(self) -> list[str]:
        """Return the body of the function `where`: the joins and the conditions of the filter."""
        lines: list[str] = []
        f = self.filter
        if f is not None and f.today:
            lines.append("day = moment.date()")
        for alias, (_, condition) in f.joins.items() if f is not None else ():
            lines.append(render(Call("statement.outerjoin", (alias, condition)), 4, "statement = "))
        for condition in f.where if f is not None else ():
            lines.append(render(Call("statement.where", (condition,)), 4, "statement = "))
        lines.append("return statement")
        return lines

    def due_lines(self) -> list[str]:
        """Return the body of the function `due` of a job with an entity, at an indent of 4."""
        assert self.entity is not None
        entity = self.entity.name
        if self.schedule is not None:
            return [
                "time = SCHEDULE.last(now, window)",
                "if time is None:",
                "    return []",
                f"ids = await session.scalars(where(select({entity}.id), now))",
                "return [jobs.Due(id, time) for id in ids]",
            ]
        assert self.at is not None
        column = f"{entity}.{self.at.attr}"
        if self.at.type == "date":
            bounds = (f"{column} > (end - window).date()", f"{column} <= end.date()")
            time = "dt.datetime.combine(value, dt.time(), dt.UTC) + OFFSET"
        else:
            bounds = (f"{column} > end - window", f"{column} <= end")
            time = "value + OFFSET"
        clauses = ["for id, value in rows"]
        if not self.at.required:
            # The bounds leave out the records without a value, but the type does not know it.
            clauses.append("if value is not None")
        return [
            "end = now - OFFSET",
            f"statement = select({entity}.id, {column})",
            render(Call("statement.where", bounds), 4, "statement = "),
            "rows = await session.execute(where(statement, now))",
            _comprehension("return ", f"jobs.Due(id, {time})", clauses, 4),
        ]

    def imports(self) -> str:
        """Return the import block of the module of the job."""
        code = " ".join([*self.where_lines(), *(self.due_lines() if self.entity else [])])
        lines = {
            "import datetime as dt",
            "from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker",
            "from app.core.config import Settings",
        }
        lines.add("from app.core import jobs")
        if self.entity is None:
            lines.add(f"from app.jobs import {self.module}_ext")
            return import_block(lines)
        entity = self.entity
        operation = self.operation
        assert operation is not None
        sql = {"Select", "select"}
        sql |= {n for n in ("and_", "false", "not_", "or_", "true") if f"{n}(" in code}
        lines.add(from_import("sqlalchemy", sql))
        joins = self.filter.joins if self.filter is not None else {}
        if joins:
            lines.add("from sqlalchemy.orm import aliased")
        if "Decimal(" in code:
            lines.add("from decimal import Decimal")
        if "UUID(" in code:
            lines.add("from uuid import UUID")
        if "day_start(" in code:
            lines.add("from app.core.pagination import day_start")
        lines.add(f"from app.features.{entity.slice} import {operation.name}_ext")
        if operation.params:
            lines.add(f"from app.features.{entity.slice}.schemas import {operation.params_class}")
        classes = {entity.name} | {cls for cls, _ in joins.values()}
        enums: dict[str, set[str]] = {}
        for e in entity.app_entities.values():
            if f"{e.name}." in code or f"({e.name})" in code:
                classes.add(e.name)
            for enum in (f.enum for f in e.fields if f.enum is not None):
                if enum.name + "." in code:
                    enums.setdefault(e.slice, set()).add(enum.name)
        lines.add(from_import("app.models", classes))
        for slice_name, names in enums.items():
            lines.add(from_import(f"app.features.{slice_name}.enums", names))
        lines |= {
            f"from app.integrations.{c.module}.client import {c.client}" for c in self.clients
        }
        if self.user_clients:
            lines.add("from app.core.connections import connected")
        return import_block(lines)

    @property
    def user_clients(self) -> list[PyJobClient]:
        """The clients that send the token of the user of the record (ADR 0033)."""
        return [c for c in self.clients if c.user is not None]

    def test_imports(self) -> str:
        """Return the import block of the generated tests of the job."""
        lines = {
            "import asyncio",
            "import datetime as dt",
            "import logging",
            "import pytest",
            "from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker",
            "from app.core.config import Settings",
            "from app.core.db import make_engine, make_sessions",
            "from app.core.jobs import JobRun",
        }
        sql = {"select"}
        if self.entity is None:
            lines.add(from_import("app.jobs", {self.module, f"{self.module}_ext"}))
            lines.add(from_import("sqlalchemy", sql))
            return import_block(lines)
        entity = self.entity
        assert self.operation is not None
        test = self.test
        values = [*test.passing.values()] if test is not None else []
        if test is not None and test.failing is not None:
            values.append(test.failing[1])
        code = " ".join(values)
        if self.at is not None or values:
            sql.add("update")
        if test is None:
            sql.add("Select")
        lines |= {
            from_import("sqlalchemy", sql),
            "from uuid import UUID",
            f"from app.features.{entity.slice} import {self.operation.name}_ext",
            f"from app.jobs import {self.module}",
            f"from app.models import {entity.name}",
            f"from tests.factories import make_{entity.snake}",
        }
        if "Decimal(" in code:
            lines.add("from decimal import Decimal")
        enums = {f.enum.name for f in entity.fields if f.enum is not None}
        if found := {name for name in enums if f"{name}." in code}:
            lines.add(from_import(f"app.features.{entity.slice}.enums", found))
        return import_block(lines)

    def record_values(self) -> list[str]:
        """Return the values that the tests set on a record: the time of `at`, and the filter."""
        found = [f"{self.at.attr}=value"] if self.at is not None else []
        test = self.test
        for attr, value in test.passing.items() if test is not None else ():
            if test is not None and test.failing is not None and test.failing[0] == attr:
                other = test.failing[1]
                if (value, other) == ("True", "False"):
                    value = "passes"
                elif (value, other) == ("False", "True"):
                    value = "not passes"
                else:
                    value = f"{value} if passes else {other}"
            found.append(f"{attr}={value}")
        return found

    def aliases(self) -> list[tuple[str, str]]:
        """The aliases of the joined entities: the name and the class."""
        joins = self.filter.joins if self.filter is not None else {}
        return sorted((alias, cls) for alias, (cls, _) in joins.items())

    def run_args(self) -> list[str]:
        """Return the arguments of the call of the operation: the record, the params, the APIs."""
        assert self.operation is not None
        args = ["session", "record"]
        if self.operation.params:
            args.append(f"{self.operation.params_class}()")
        return args + [c.param for c in self.clients]

    def test_times(self) -> tuple[str, str]:
        """Return the Python code of the time of a record of a test and of its run (`at`)."""
        assert self.at is not None
        if self.at.type == "date":
            value = f"dt.date({TEST_TIME.year}, {TEST_TIME.month}, {TEST_TIME.day})"
            return value, f"dt.datetime.combine(VALUE, dt.time(), dt.UTC) + {self.name}.OFFSET"
        return _datetime_code(TEST_TIME), f"VALUE + {self.name}.OFFSET"

    def run_time(self) -> dt.datetime:
        """Return the time of the run of the first record of a test (`at`), or the schedule."""
        if self.schedule is not None:
            return self.schedule.times()[0]
        assert self.at is not None
        delta = parse_offset(self.offset)
        if self.at.type == "date":
            return dt.datetime.combine(TEST_TIME.date(), dt.time(), dt.UTC) + delta
        return TEST_TIME + delta


def python_jobs(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    operations: dict[str, PyOperation],
) -> dict[str, PyJob]:
    """Return the jobs of the definition, by name.

    Raise GenerationError if a job has a name that the modules need, or if
    its filter reads a computed field.
    """
    found: dict[str, PyJob] = {}
    calls = any(
        definition.operations[job.operation].apis
        for job in definition.jobs.values()
        if job.operation is not None
    )
    apis = python_apis(definition) if calls else {}
    for name, job in definition.jobs.items():
        if name in _MODULES or (
            name.endswith("_ext") and name.removesuffix("_ext") in definition.jobs
        ):
            raise GenerationError(
                f"The job '{name}' has the name of a module of `app/jobs/`. Give it another name."
            )
        result = PyJob(name=name, id=job.id, description=job.description)
        if job.schedule is not None:
            result.schedule = PySchedule(parse_cron(job.schedule))
        if job.entity is not None:
            entity = entities[job.entity]
            assert job.operation is not None
            result.entity = entity
            result.operation = operations[job.operation]
            for api in (apis[a] for a in result.operation.apis):
                client = PyJobClient(api.param, api.client, api.settings_args(), api.module)
                if api.user:
                    # The client sends the token of the user of the record (ADR 0033).
                    user = f"record.{_user_attr(entity, job.user)}"
                    args = ["settings", "sessions", user]
                    client = PyJobClient(
                        api.param, api.client_for, args, api.module, api.name, user
                    )
                result.clients.append(client)
            if job.at is not None:
                result.at = next(f for f in entity.fields if f.name == job.at)
                result.offset = job.offset or "0m"
            result.filter = PyJobFilter(job.id, entity)
            builder = FilterBuilder(definition, result.filter, "job")
            for path, condition in job.filter.items():
                builder.filter(path, condition)
            result.test = _test(definition, result, job.filter)
        found[name] = result
    return found


def _user_attr(entity: PyEntity, user: str | None) -> str:
    """Return the attribute of a record with the ID of the user of a job: `id` for the user
    entity, else the foreign key of the relation. The validator checks the relation."""
    if user is None or user == "id":
        return "id"
    relation = next(r for r in entity.relations if r.name == user)
    assert relation.fk_attr is not None
    return relation.fk_attr


def _test(
    definition: AppDefinition, job: PyJob, record_filter: dict[str, JsonValue]
) -> PyJobTest | None:
    """Plan the values of the filter fields of the test records, or None if a test cannot."""
    assert job.entity is not None
    entity = job.entity
    # The date of the pass of the tests: one minute after the time of the run.
    values = FilterValues(definition, entity, (job.run_time() + dt.timedelta(minutes=1)).date())
    passing: dict[str, str] = {}
    failing: tuple[str, str] | None = None
    now = False
    unique = {c for r in entity.unique_rules for c in r.columns}
    for path, condition in record_filter.items():
        f = values.direct_field(path)
        if f is None or f.unique or f.name in unique or (job.at and f.name == job.at.name):
            return None
        conditions: dict[str, JsonValue] = (
            condition
            if isinstance(condition, dict)
            else {"in" if isinstance(condition, list) else "eq": condition}
        )
        found = values.values(f, conditions)
        if found is None or not found[0]:
            return None
        passes, fails = found
        passing[f.attr] = passes[0].code
        if failing is None and fails:
            failing = (f.attr, fails[0].code)
        now = now or "now" in passes[0].code or bool(fails and "now" in fails[0].code)
    return PyJobTest(passing, failing, now)


def _comprehension(prefix: str, element: str, clauses: list[str], indent: int) -> str:
    """Return a list comprehension in the format of the Ruff formatter, without the first indent."""
    inner = " ".join([element, *clauses])
    if indent + len(prefix) + len(inner) + 2 <= LINE_LENGTH:
        return f"{prefix}[{inner}]"
    pad = " " * (indent + 4)
    if len(pad) + len(inner) <= LINE_LENGTH:
        return f"{prefix}[\n{pad}{inner}\n{' ' * indent}]"
    body = "".join(f"{pad}{part}\n" for part in [element, *clauses])
    return f"{prefix}[\n{body}{' ' * indent}]"


def _set(values: frozenset[int], low: int, high: int) -> str:
    """Return a set of the values of a field of a schedule as Python code."""
    ordered = sorted(values)
    if ordered == list(range(ordered[0], ordered[-1] + 1)) and len(ordered) > 2:
        start = "" if ordered[0] == 0 else f"{ordered[0]}, "
        return f"frozenset(range({start}{ordered[-1] + 1}))"
    return "frozenset({" + ", ".join(str(v) for v in ordered) + "})"


def _datetime_code(time: dt.datetime) -> str:
    parts = [time.year, time.month, time.day, time.hour]
    if time.minute:
        parts.append(time.minute)
    return f"dt.datetime({', '.join(str(p) for p in parts)}, tzinfo=dt.UTC)"
