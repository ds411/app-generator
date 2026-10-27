"""The jobs of the Next.js app: one route handler for each job (ADR 0029).

The Next.js app has no long-running process. A scheduler calls the route
`/api/jobs/<job>` with the secret `JOBS_SECRET`: a Kubernetes CronJob,
Cloud Scheduler, or the loop of the service `jobs` in Compose. Each call
runs the runs of the job that are due in the window before the time of
the call, so a call at any time runs each run one time. The module
`src/app/jobs/<job>.ts` selects the records with the filter of the job,
and calls the custom operation on each record, in the transaction of the
run. `src/shared/lib/jobs.ts` keeps the runs in the table `job_runs`, the
same table as in the FastAPI app.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue

from appgen.bindings.nextjs.db import Table, TsCall, TsChain, TsCode, format_ts
from appgen.dsl.auth import ME
from appgen.dsl.cron import Cron, parse_cron
from appgen.dsl.model import AppDefinition, Field, Relation
from appgen.gen.naming import camel, kebab
from appgen.gen.render import GenerationError

TABLE = "job_runs"
"""The table of the runs of the jobs. The FastAPI app has the same table."""
TABLE_CONST = "jobRunsTable"
TABLE_MODULE = "job-runs"

_OPERATORS = (
    *("and", "eq", "gt", "gte", "inArray", "isNotNull", "isNull"),
    *("lt", "lte", "ne", "notInArray", "or"),
)
"""The functions of `drizzle-orm` that the module of a job can call."""
_HELPERS = ("dateOf", "dayStart", "runDue", "Schedule", "span")
"""The functions of `@/shared/lib/jobs` that the module of a job can call."""


@dataclass(slots=True)
class TsSchedule:
    """The cron schedule of a job, in UTC."""

    cron: Cron

    @property
    def expression(self) -> str:
        return self.cron.expression

    def code(self) -> str:
        """Return the `new Schedule(...)` construction of the job module."""
        sets = (
            ("minutes", self.cron.minutes),
            ("hours", self.cron.hours),
            ("days", self.cron.days),
            ("months", self.cron.months),
            ("weekdays", self.cron.weekdays),
        )
        lines = [f"  {name}: {_span(values)}," for name, values in sets]
        if self.cron.either_day:
            lines.append("  eitherDay: true,")
        return "\n".join(
            [f"const SCHEDULE = new Schedule({json.dumps(self.expression)}, {{", *lines, "});"]
        )


@dataclass(slots=True)
class TsFilter:
    """The Drizzle condition of the filter of a job, with what it reads."""

    code: TsCode | None = None
    """The expression, of the parameters `now` and `today`, or None for no filter."""
    tables: set[str] = field(default_factory=set[str])
    """The tables of `@/shared/db` that the condition reads."""
    today: bool = False
    now: bool = False
    me: bool = False
    """True if the condition reads `me`, the ID of the signed-in user or null (`$me`)."""


@dataclass(slots=True)
class TsJob:
    """A job: its route runs its custom operation, or its extension function, at its times."""

    name: str
    id: str
    description: str | None
    schedule: TsSchedule | None = None
    entity: str | None = None
    table: Table | None = None
    at: Field | None = None
    at_name: str | None = None
    offset: str = "0m"
    offset_ms: int = 0
    operation: str | None = None
    params: bool = False
    param_defaults: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    """The default values of the params of the operation, by TypeScript key."""
    filter: TsFilter = field(default_factory=TsFilter)
    user_key: str | None = None
    """The key of the record with the ID of the user of a run (`user`, ADR 0033), for example
    `ownerId`, or None."""
    user_required: bool = True
    """False if the record can have no user: a run for it does nothing."""
    user_apis: list[str] = field(default_factory=list[str])
    """The APIs with the authorization code flow that the operation calls."""

    @property
    def module(self) -> str:
        """The module of the job in `src/app/jobs/`, for example `booking-reminder`."""
        return kebab(self.name)

    @property
    def function(self) -> str:
        """The function of the module that runs the job, for example `runBookingReminder`."""
        name = camel(self.name)
        return "run" + name[0].upper() + name[1:]

    @property
    def gap(self) -> bool:
        """True for a job without an entity: its extension file has the logic."""
        return self.entity is None

    @property
    def ext_function(self) -> str:
        """The function of the extension file of a job without an entity."""
        return camel(self.name)

    @property
    def summary(self) -> str:
        """The sentence of the comment of the module on the times of the job."""
        if self.schedule is not None:
            return f"The job runs on the schedule `{self.schedule.expression}` (UTC)."
        offset = f" with the offset `{self.offset}`" if self.offset_ms else ""
        return f"The job runs for each record at the time of `{self.at_name}`{offset}."

    @property
    def when(self) -> str:
        """The times of the job for the table of the README."""
        if self.schedule is not None:
            return f"The schedule `{self.schedule.expression}`"
        offset = f" {self.offset}" if self.offset_ms else ""
        return f"The time of `{self.at_name}`{offset}"

    @property
    def where_param(self) -> str:
        """The parameter of the function `where`: the time, if the filter reads it."""
        return "now: Date" if self.filter.now or self.filter.today else ""

    @property
    def where_call(self) -> str:
        return "where(now)" if self.where_param else "where()"

    def where_code(self) -> str:
        """Return the body of the function `where`."""
        assert self.filter.code is not None
        lines = ["const today = dateOf(now);"] if self.filter.today else []
        return _block([*lines, format_ts(self.filter.code, 2, "return ", ";")], 2)

    def due_code(self) -> str:
        """Return the body of the function `due` of a job with an entity."""
        assert self.table is not None
        table = self.table.const
        conditions: list[TsCode] = [self.where_call] if self.filter.code is not None else []
        columns = f"{{ id: {table}.id }}"
        if self.schedule is not None:
            head = [
                "const time = SCHEDULE.last(now, windowMs);",
                "if (time === null) {\n    return [];\n  }",
            ]
            result = "return rows.map((row) => ({ recordId: row.id, time }));"
        else:
            assert self.at is not None and self.at_name is not None
            column = f"{table}.{camel(self.at_name)}"
            columns = f"{{ id: {table}.id, value: {column} }}"
            if self.at.type == "date":
                bounds = ("dateOf(end - windowMs)", "dateOf(end)")
                time = "new Date(dayStart(row.value).getTime() + OFFSET_MS)"
            else:
                bounds = ("new Date(end - windowMs)", "new Date(end)")
                time = "new Date(row.value.getTime() + OFFSET_MS)"
            head = ["const end = now.getTime() - OFFSET_MS;"]
            conditions = [
                TsCall("gt", [column, bounds[0]]),
                TsCall("lte", [column, bounds[1]]),
                *conditions,
            ]
            if self.at.required:
                result = (
                    "return rows.map((row) => ({\n"
                    f"    recordId: row.id,\n    time: {time},\n  }}));"
                )
            else:
                # The bounds leave out the records without a value, but the type does not know it.
                item = f"{{ recordId: row.id, time: {time} }}"
                result = (
                    f"return rows.flatMap((row) =>\n    row.value === null ? [] : [{item}],\n  );"
                )
        calls = [TsCall("select", [columns]), TsCall("from", [table])]
        if conditions:
            where = conditions[0] if len(conditions) == 1 else TsCall("and", conditions)
            calls.append(TsCall("where", [where]))
        rows = format_ts(TsChain("getDb()", calls), 2, "const rows = await ", ";")
        return _block([*head, rows, result], 2)

    def action_code(self) -> str:
        """Return the body of the action of a run of a job with an entity."""
        assert self.table is not None and self.entity is not None and self.operation is not None
        table = self.table.const
        lines: list[str] = []
        if self.filter.code is not None:
            selected = TsCall("and", [f"eq({table}.id, item.recordId)", self.where_call])
            lines += [
                format_ts(selected, 4, "const selected = ", ";"),
                f"if ((await getDb().$count({table}, selected)) === 0) {{\n"
                "      // The filter does not select the record any more.\n"
                "      return;\n"
                "    }",
            ]
        lines.append(f"const record = await {camel(self.entity)}Repository.get(item.recordId);")
        args: list[TsCode] = ["record"]
        if self.params:
            # The params have their default values, as in the FastAPI app.
            values = [
                f"{key}: {json.dumps(value, ensure_ascii=False)}"
                for key, value in self.param_defaults.items()
            ]
            given = "{ " + ", ".join(values) + " }" if values else "{}"
            args.append(f"{camel(self.operation)}ParamsSchema.parse({given})")
        call = TsCall(camel(self.operation), args)
        if self.user_key is None:
            lines.append(format_ts(call, 4, "await ", ";"))
            return _block(lines, 4)
        # The clients of the APIs send the token of the user of the record (ADR 0033).
        lines.append(f"const userId = record.{self.user_key};")
        checks = [f"!(await connected({json.dumps(api)}, userId))" for api in self.user_apis]
        if not self.user_required:
            checks.insert(0, "userId === null")
        if checks:
            lines.append(
                f"if ({' || '.join(checks)}) {{\n"
                "      // The user has not connected an API of the operation: do nothing.\n"
                "      return;\n"
                "    }"
            )
        work = f"() => {call.name}({', '.join(str(arg) for arg in args)})"
        lines.append(format_ts(TsCall("asUser", ["userId", work]), 4, "await ", ";"))
        return _block(lines, 4)

    def imports(self) -> list[str]:
        """Return the import lines of the module of the job, after `server-only`."""
        code = " ".join(
            [
                self.where_code() if self.filter.code is not None else "",
                self.due_code() + self.action_code() if self.entity is not None else "",
                "runDue(" + (" Schedule(" if self.schedule is not None else ""),
                "span(" if self.schedule is not None and "span(" in self.schedule.code() else "",
            ]
        )
        groups: list[list[str]] = []
        drizzle = [n for n in _OPERATORS if f"{n}(" in code]
        if self.filter.code is not None:
            drizzle.append("type SQL")
        if "sql`" in code:
            drizzle.append("sql")
        if drizzle:
            groups.append([_import("drizzle-orm", drizzle)])
        app: list[str] = []
        if self.entity is not None:
            assert self.operation is not None and self.table is not None
            entity, operation = kebab(self.entity), kebab(self.operation)
            if self.params:
                schema = f"{camel(self.operation)}ParamsSchema"
                app.append(_import(f"@/entities/{entity}", [schema]))
            app.append(_import(f"@/entities/{entity}/server", [f"{camel(self.entity)}Repository"]))
            app.append(
                _import(f"@/features/{operation}/api/{operation}.ext", [camel(self.operation)])
            )
            if self.user_key is not None:
                names = ["asUser", "connected"] if self.user_apis else ["asUser"]
                app.append(_import("@/shared/auth/connections", names))
            tables = self.filter.tables | {self.table.const}
            app.append(_import("@/shared/db", ["getDb", *tables]))
        types = ["type JobResult"]
        if self.entity is not None:
            types.append("type RecordDue")
        helpers = [n for n in _HELPERS if f"{n}(" in code]
        app.append(_import("@/shared/lib/jobs", [*types, *helpers]))
        groups.append(app)
        if self.gap:
            groups.append([_import(f"./{self.module}.ext", [self.ext_function])])
        return [line for group in groups for line in ["", *group]][1:]


def ts_jobs(definition: AppDefinition, tables: dict[str, Table]) -> dict[str, TsJob]:
    """Return the jobs of the definition, by name.

    Raise GenerationError if a table of the app has the name of the table
    of the runs, or if the filter of a job reads a computed field.
    """
    if not definition.jobs:
        return {}
    for table in tables.values():
        names = {table.name, *(j.name for j in table.join_tables)}
        if TABLE in names or table.const == TABLE_CONST or table.module == TABLE_MODULE:
            raise GenerationError(
                f"The entity '{table.entity}' has the table '{TABLE}', or its module, and the "
                "runs of the jobs need it. Give the entity another name or table."
            )
    found: dict[str, TsJob] = {}
    for name, job in definition.jobs.items():
        result = TsJob(name=name, id=job.id, description=job.description)
        if job.schedule is not None:
            result.schedule = TsSchedule(parse_cron(job.schedule))
        if job.entity is not None:
            assert job.operation is not None
            entity = definition.entities[job.entity]
            result.entity = job.entity
            result.table = tables[job.entity]
            result.operation = job.operation
            params = definition.operations[job.operation].params
            result.params = bool(params)
            result.param_defaults = {
                camel(name): param.default
                for name, param in params.items()
                if param.default is not None
            }
            if job.at is not None:
                result.at = entity.fields[job.at]
                result.at_name = job.at
                result.offset = job.offset or "0m"
                result.offset_ms = int(job.offset_delta().total_seconds() * 1000)
            if job.user is not None:
                relation = entity.relations.get(job.user)
                result.user_key = "id" if relation is None else f"{camel(job.user)}Id"
                result.user_required = relation is None or relation.required
                result.user_apis = [
                    api
                    for api in definition.operations[job.operation].apis
                    if definition.apis[api].user_flow
                ]
            builder = FilterBuilder(definition, tables, job.id, result.filter)
            conditions = [builder.filter(job.entity, path, c) for path, c in job.filter.items()]
            if conditions:
                result.filter.code = (
                    conditions[0] if len(conditions) == 1 else TsCall("and", conditions)
                )
        found[name] = result
    return found


@dataclass(frozen=True, slots=True)
class CronJob:
    """A Kubernetes CronJob that calls the routes of jobs: on a schedule, or each minute."""

    name: str
    schedule: str
    jobs: list[str]
    ids: list[str]
    """The element IDs of the jobs, for the traces."""


CRON_JOB_NAME_LENGTH = 52
"""The longest name of a CronJob: Kubernetes adds 11 characters to the names of its Jobs."""


def cron_jobs(base: str, jobs: dict[str, TsJob]) -> list[CronJob]:
    """Return the CronJobs of the jobs: one for each job with a schedule, and one each minute
    for the jobs with `at`. `base` is the name of the Kubernetes objects of the app."""
    found = [
        CronJob(_cron_job_name(base, job.module), job.schedule.expression, [name], [job.id])
        for name, job in jobs.items()
        if job.schedule is not None
    ]
    timed = [job for job in jobs.values() if job.schedule is None]
    if timed:
        name = _cron_job_name(base, "each-minute")
        found.append(CronJob(name, "* * * * *", [j.name for j in timed], [j.id for j in timed]))
    return found


def _cron_job_name(base: str, suffix: str) -> str:
    name = f"{base}-{suffix}"
    if len(name) <= CRON_JOB_NAME_LENGTH:
        return name
    digest = hashlib.sha256(name.encode()).hexdigest()[:6]
    return f"{name[: CRON_JOB_NAME_LENGTH - 7].rstrip('-')}-{digest}"


def _block(statements: list[str], indent: int) -> str:
    """Return statements on their lines at an indent. The later lines of a statement have
    their indent already."""
    return "\n".join(" " * indent + statement for statement in statements)


def _import(module: str, names: Sequence[str]) -> str:
    """Return an import line with the names sorted as in the other modules of the app."""
    ordered = sorted(set(names), key=lambda name: name.removeprefix("type ").lower())
    return f'import {{ {", ".join(ordered)} }} from "{module}";'


def _span(values: frozenset[int]) -> str:
    """Return the values of a field of a schedule as TypeScript: a range, or a list."""
    ordered = sorted(values)
    if len(ordered) > 2 and ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"span({ordered[0]}, {ordered[-1]})"
    return "[" + ", ".join(str(v) for v in ordered) + "]"


@dataclass(frozen=True, slots=True)
class _Hop:
    """A relation to one record on a field path: the entity before it, and the relation."""

    entity: str
    name: str
    relation: Relation


class FilterBuilder:
    """Builds the Drizzle condition of the filter of a job, as the FastAPI app does.

    A path through a relation to one record is a subquery of the IDs of the
    related records. As with the outer join of the FastAPI app, a record
    without a related record passes a condition that passes a missing
    value (`ne`, `not_in`, and `eq` with null). The totals (ADR 0034) use
    it for the filters of their related records.
    """

    def __init__(
        self, definition: AppDefinition, tables: dict[str, Table], job: str, found: TsFilter
    ) -> None:
        self.definition = definition
        self.tables = tables
        self.job = job
        self.found = found

    def table(self, entity: str) -> str:
        const = self.tables[entity].const
        self.found.tables.add(const)
        return const

    def filter(self, entity: str, path: str, condition: JsonValue) -> TsCode:
        conditions: dict[str, JsonValue] = (
            condition
            if isinstance(condition, dict)
            else {"in" if isinstance(condition, list) else "eq": condition}
        )
        parts = [self.path(entity, path, op, operand) for op, operand in conditions.items()]
        return parts[0] if len(parts) == 1 else TsCall("and", parts)

    def path(self, entity: str, path: str, op: str, operand: JsonValue) -> TsCode:
        """Return the condition of one operator on a path, with the subqueries of its hops."""
        hops: list[_Hop] = []
        segments = path.split(".")
        current = entity
        for segment in segments[:-1]:
            relation = self.definition.entities[current].relations[segment]
            hops.append(_Hop(current, segment, relation))
            current = relation.target
        inner, missing = self.end(current, segments[-1], op, operand)
        for hop in reversed(hops):
            inner = self.hop(hop, inner, missing)
        return inner

    def hop(self, hop: _Hop, inner: TsCode, missing: bool) -> TsCode:
        """Return the condition on the records before a hop, of a condition after it."""
        table = self.table(hop.entity)
        target = self.table(hop.relation.target)
        column = self.column_of_relation(hop.entity, hop.name)
        if column is not None:
            ids = _select(f"{target}.id", target, inner)
            matches: TsCode = TsCall("inArray", [f"{table}.{column}", ids])
            if missing:
                return TsCall("or", [TsCall("isNull", [f"{table}.{column}"]), matches])
            return matches
        # The target has the foreign key (a one_to_one relation that the target stores).
        foreign = self.foreign_key(hop.entity, hop.name)
        matches = TsCall("inArray", [f"{table}.id", _select(f"{target}.{foreign}", target, inner)])
        if not missing:
            return matches
        linked = _select(
            f"{target}.{foreign}", target, TsCall("isNotNull", [f"{target}.{foreign}"])
        )
        none = TsCall("notInArray", [f"{table}.id", linked])
        return TsCall("or", [none, matches])

    def column_of_relation(self, entity: str, name: str) -> str | None:
        """Return the foreign key column of a relation on the table of the entity, or None."""
        relation_id = self.definition.entities[entity].relations[name].id
        table = self.tables[entity]
        return next((c.key for c in table.columns if c.element_id == relation_id), None)

    def foreign_key(self, entity: str, name: str) -> str:
        relation_id = self.definition.entities[entity].relations[name].id
        table = self.tables[entity]
        return next(i.foreign_key for i in table.inverse_ones if i.element_id == relation_id)

    def end(self, entity: str, name: str, op: str, operand: JsonValue) -> tuple[TsCode, bool]:
        """Return the condition of the last segment of a path, and if a missing value passes it."""
        spec = self.definition.entities[entity]
        table = self.table(entity)
        operands = operand if isinstance(operand, list) else [operand]
        missing = (op in ("ne", "not_in") and None not in operands) or (
            op in ("eq", "in") and None in operands
        )
        if name in spec.fields and spec.fields[name].computed is not None:
            raise GenerationError(
                f"The job '{self.job}' reads the computed field '{entity}.{name}'. The Next.js "
                "app selects the records of a job in the database, and a computed field has no "
                "column. Use a stored field."
            )
        if name == "id":
            return self.compare(f"{table}.id", None, op, operand), missing
        if name in spec.fields:
            f = spec.fields[name]
            return self.compare(f"{table}.{camel(name)}", f, op, operand), missing
        relation = spec.relations[name]
        column = self.column_of_relation(entity, name)
        if column is not None:
            return self.compare(f"{table}.{column}", None, op, operand), missing
        if relation.kind == "one_to_one":
            hop = _Hop(entity, name, relation)
            inner = self.compare(f"{self.table(relation.target)}.id", None, op, operand)
            return self.hop(hop, inner, missing), False
        return self.many(entity, name, relation, op, operands), False

    def many(
        self, entity: str, name: str, relation: Relation, op: str, operands: Sequence[JsonValue]
    ) -> TsCode:
        """Return a condition on the IDs of a relation to many records: one of them, or none."""
        table = self.table(entity)
        ids = [json.dumps(o) for o in operands if o is not None]
        if op not in ("eq", "in", "ne", "not_in") or (not ids and op in ("eq", "in")):
            return self.sql("false")
        if not ids:
            return self.sql("true")
        listed = "[" + ", ".join(ids) + "]"
        if relation.kind == "one_to_many":
            target = self.table(relation.target)
            inverse = relation.inverse
            assert inverse is not None
            foreign = f"{target}.{camel(inverse)}Id"
            owners = _select(
                foreign,
                target,
                TsCall(
                    "and",
                    [
                        TsCall("inArray", [f"{target}.id", listed]),
                        TsCall("isNotNull", [foreign]),
                    ],
                ),
            )
        else:
            join = next(
                item for item in self.tables[entity].lists if item.element_id == relation.id
            )
            self.found.tables.add(join.join_const)
            owners = _select(
                f"{join.join_const}.{join.owner_key}",
                join.join_const,
                TsCall("inArray", [f"{join.join_const}.{join.target_key}", listed]),
            )
        name_of = "inArray" if op in ("eq", "in") else "notInArray"
        return TsCall(name_of, [f"{table}.id", owners])

    def sql(self, text: str) -> str:
        return f"sql`{text}`"

    def compare(self, column: str, f: Field | None, op: str, operand: JsonValue) -> TsCode:
        """Return the condition of one operator on a column, as the FastAPI app does."""
        field_type = f.type if f is not None else "uuid"
        operands = operand if isinstance(operand, list) else [operand]
        if operands and all(o == ME for o in operands):
            return self.me(column, op)
        if field_type == "datetime" and all(_is_day(o) for o in operands if o is not None):
            days = [self.literal(f, o, day=True) for o in operands if o is not None]
            return self.by_day(column, op, days)
        if op in ("eq", "ne") and operand is None:
            return TsCall("isNull" if op == "eq" else "isNotNull", [column])
        if op == "eq":
            return TsCall("eq", [column, self.literal(f, operand)])
        if op == "ne":
            different = TsCall("ne", [column, self.literal(f, operand)])
            return TsCall("or", [TsCall("isNull", [column]), different])
        if op in ("in", "not_in"):
            values = [self.literal(f, o) for o in operands if o is not None]
            has_null = None in operands
            if not values:
                if op == "in":
                    return TsCall("isNull", [column]) if has_null else self.sql("false")
                return TsCall("isNotNull", [column]) if has_null else self.sql("true")
            listed = "[" + ", ".join(values) + "]"
            if op == "in":
                found = TsCall("inArray", [column, listed])
                return TsCall("or", [TsCall("isNull", [column]), found]) if has_null else found
            other = TsCall("notInArray", [column, listed])
            if has_null:
                return other
            return TsCall("or", [TsCall("isNull", [column]), other])
        if operand is None:
            return self.sql("false")
        return TsCall(op, [column, self.literal(f, operand)])

    def me(self, column: str, op: str) -> TsCode:
        """Return the condition of `$me`: without a signed-in user, no record has the value."""
        self.found.me = True
        if op in ("eq", "in"):
            same = format_ts(TsCall("eq", [column, "me"]), 0)
            return f"me === null ? {self.sql('false')} : {same}"
        other = TsCall("or", [TsCall("isNull", [column]), TsCall("ne", [column, "me"])])
        return f"me === null ? {self.sql('true')} : {format_ts(other, 0)}"

    def by_day(self, column: str, op: str, days: list[str]) -> TsCode:
        """Return a condition of a date-time column and dates: the days in UTC."""

        def start(day: str, after: bool = False) -> str:
            return f"dayStart({day}, 1)" if after else f"dayStart({day})"

        def on(day: str) -> TsCode:
            return TsCall(
                "and",
                [
                    TsCall("gte", [column, start(day)]),
                    TsCall("lt", [column, start(day, True)]),
                ],
            )

        def off(day: str) -> TsCode:
            return TsCall(
                "or",
                [
                    TsCall("lt", [column, start(day)]),
                    TsCall("gte", [column, start(day, True)]),
                ],
            )

        day = days[0]
        match op:
            case "eq":
                return on(day)
            case "in":
                return on(day) if len(days) == 1 else TsCall("or", [on(d) for d in days])
            case "ne" | "not_in":
                offs = [off(d) for d in days]
                rest = offs[0] if len(offs) == 1 else TsCall("and", list(offs))
                return TsCall("or", [TsCall("isNull", [column]), rest])
            case "lt":
                return TsCall("lt", [column, start(day)])
            case "lte":
                return TsCall("lt", [column, start(day, True)])
            case "gt":
                return TsCall("gte", [column, start(day, True)])
            case _:
                return TsCall("gte", [column, start(day)])

    def literal(self, f: Field | None, value: JsonValue, *, day: bool = False) -> str:
        """Return a value of the filter as a TypeScript expression for a column."""
        field_type = f.type if f is not None else "uuid"
        if value == "$today" or (value == "$now" and (day or field_type == "date")):
            self.found.today = True
            return "today"
        if value == "$now":
            self.found.now = True
            return "now"
        if field_type == "datetime" and not day:
            return f"new Date({json.dumps(value)})"
        if field_type in ("integer", "decimal", "boolean"):
            return json.dumps(value)
        return json.dumps(value, ensure_ascii=False)


def _select(column: str, table: str, where: TsCode) -> TsChain:
    """Return the subquery of one column of the rows of a table that pass a condition."""
    return TsChain(
        "getDb()",
        [
            TsCall("select", [f"{{ id: {column} }}"]),
            TsCall("from", [table]),
            TsCall("where", [where]),
        ],
    )


def _is_day(value: JsonValue) -> bool:
    """Return True for `$today`, and for a date without a time."""
    return value == "$today" or (isinstance(value, str) and len(value) == 10)
