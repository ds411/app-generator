"""The endpoints of the dashboards: the database computes the values of the widgets.

Each `stat`, `chart`, and `list` widget of a dashboard gets an endpoint
`GET /dashboards/<dashboard>/<widget>`, so that a client gets the value
of a widget without the records. A stat gives its aggregate (`count`,
`sum`, `avg`, `min`, or `max`), a chart gives the aggregate of each
group that has records, and a list gives its first records in the order
of the widget. A chart of dates groups them by day, week, month, or
year (`interval`): a week starts on the day `week_start` of the endpoint.

The filter of a widget is a `WHERE` clause with the semantics of the
browser: an empty value is not equal to a value, and passes no
comparison. A field path through relations joins the related records
(`LEFT OUTER JOIN`). On a date-time field, a date compares by the day
in UTC. `$today` is the parameter `today` of the endpoint, else the
date in UTC, and `$now` is the time of the request.

An endpoint needs the permission of the list operation of its entity,
and reads only the records of the record rule of the role (ADR 0025). A
list widget hides the embedded records that the rules hide. The binding reads
the widgets of the definition, but the `ui` kinds stay out of its
coverage (ADR 0006).
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, cast

from pydantic import JsonValue

from appgen.bindings.fastapi.pysource import LINE_LENGTH, call, from_import, import_block, string
from appgen.bindings.fastapi.queries import Call, Expr, PyPath, render, resolve_path
from appgen.bindings.shared.views import definition_display
from appgen.dsl.auth import ME
from appgen.dsl.model import AppDefinition
from appgen.dsl.model import Field as DslField
from appgen.dsl.ui.dashboards import ChartWidget, ListWidget, StatWidget
from appgen.dsl.ui.views import CardsView, Sort, TableView
from appgen.gen.naming import constant, kebab, snake
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyField

PREFIX = "/dashboards"
"""The URL prefix of the dashboard endpoints."""
SLICE = "dashboards"
"""The slice of the dashboards in `app/features/`."""
TEST_TODAY = dt.date(2026, 6, 15)
TEST_PERIOD = (TEST_TODAY - dt.timedelta(days=29), TEST_TODAY)
"""The first and the last day of the period that the generated tests send as `start` and `end`."""
"""The date that the generated tests send as `today`."""
_MODULES = frozenset({"router", "schemas", "aggregates"})
"""The modules of the slice: a dashboard cannot have their names."""
_NUMBER_TYPES = frozenset({"integer", "decimal"})
_TEST_TYPES = frozenset({"enum", "boolean", "integer", "decimal", "date", "datetime"})
"""The field types that a generated test can give known values."""
_STEPS = range(-3, 4)
_LIST_CHECK = 'assert [item["id"] for item in response.json()] == ids'
"""The steps around each operand of a filter, for the values of a test."""


@dataclass(slots=True)
class TestValue:
    """A value of a field in a generated test: the Python code, and the value to compare."""

    code: str
    value: object
    """A date, a number, a text, a boolean, or the days after now (`$now`)."""


@dataclass(slots=True)
class WidgetTest:
    """The records of a generated test: the values of each record, and the expected result.

    The first `passing` records pass the filter. Each next record fails one
    path of the filter. `parents` is the count of parent records that a
    chart of a relation needs.
    """

    records: list[dict[str, str]]
    """The attributes and the Python values of each record."""
    passing: int
    checks: list[str]
    """The lines that check the response, at an indent of 4."""
    parents: tuple[PyEntity, str, int] | None = None
    """For a chart of a relation: the target, the foreign key attribute, and the count."""
    now: bool = False
    """True if the values use `now`, the time of the test."""


@dataclass(slots=True)
class PyWidget:
    """A widget of a dashboard with an endpoint."""

    name: str
    id: str
    kind: str
    """`stat`, `chart`, or `list`."""
    label: str
    operation_id: str
    """The operation ID and the function name, for example `overview_open_tasks`."""
    path: str
    """The path under the prefix of the dashboard, for example `/open-tasks`."""
    entity: PyEntity
    permission: str
    """The operation that a role needs: the list operation of the entity, else the endpoint."""
    protected: bool = False
    scoped: bool = False
    """True if a record rule of a role can limit the records (ADR 0025)."""
    hides: bool = False
    """True if a list widget hides the embedded records that a record rule hides."""
    aggregate: str = "count"
    today: bool = False
    now: bool = False
    me: bool = False
    joins: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    """The aliases of the joined entities: the class and the join condition."""
    where: list[Expr] = field(default_factory=list[Expr])
    value: str = ""
    """The aggregate expression of a stat or a chart."""
    key: Expr = ""
    """The group key expression of a chart."""
    week: bool = False
    """True if a chart groups the dates by week: the endpoint takes `week_start`."""
    period: tuple[str, bool] | None = None
    """The column of the period field, and True for a date-time: the endpoint takes `start`
    and `end`, the first and the last day of the period of the dashboard."""
    order: list[str] = field(default_factory=list[str])
    limit: int = 0
    test: WidgetTest | None = None
    snapshots: bool = False
    """True for a stat with `snapshots: daily`: its value function gives the value to the
    endpoint and to the built-in job `stat_snapshots` (ADR 0042)."""
    snapshot_of: tuple[str, str, int] | None = None
    """For a chart of snapshots: the dashboard, the stat widget, and the count of days."""

    @property
    def value_function(self) -> str:
        """The value function of a stat with snapshots, for example `overview_rooms_value`."""
        return f"{self.operation_id}_value"

    def value_params(self) -> list[str]:
        """Return the parameters of the value function: the session, the day, and the time."""
        params = ["session: AsyncSession"]
        if self.today:
            params.append("day: dt.date")
        if self.now:
            params.append("moment: dt.datetime")
        return params

    def value_lines(self) -> list[str]:
        """Return the body of the value function of a stat, at an indent of 4."""
        return [*self.statement_lines(), "return number(await session.scalar(statement))"]

    @property
    def returns(self) -> str:
        if self.kind == "stat":
            return "StatValue"
        if self.kind == "chart":
            return "ChartValues"
        return f"list[{self.entity.name}Read]"

    @property
    def empty(self) -> str:
        """The JSON of the response without records, as a Python expression."""
        if self.kind == "stat":
            return '{"value": 0}' if self.aggregate in ("count", "sum") else '{"value": None}'
        if self.kind == "chart":
            return '{"groups": []}'
        return "[]"

    def decorator(self, guard: str | None) -> str:
        """Return the route decorator of the endpoint."""
        args = [
            string(self.path),
            "responses=problem_responses(422)",
            f"summary={string(self.label)}",
            f'operation_id="{self.operation_id}"',
        ]
        if guard is not None:
            args.append(f"dependencies=[Depends({guard})]")
        return call("@router.", "get", args, 0)

    def signature(self) -> str:
        """Return the `async def` line of the endpoint function, in the format of Ruff."""
        params = ["session: SessionDep"]
        if self.scoped or self.hides:
            params.append("scope: Scope")
        if self.today:
            params.append("today: Today = None")
        if self.week:
            params.append("week_start: WeekStart = 1")
        if self.period is not None:
            params += ["start: PeriodStart = None", "end: PeriodEnd = None"]
        head = f"async def {self.operation_id}("
        tail = f") -> {self.returns}:"
        one_line = head + ", ".join(params) + tail
        if len(one_line) <= LINE_LENGTH:
            return one_line
        return head + "\n" + "".join(f"    {p},\n" for p in params) + tail

    def body(self) -> list[str]:
        """Return the lines of the body of the endpoint function, at an indent of 4."""
        if self.snapshot_of is not None:
            return self.snapshot_lines()
        if self.snapshots:
            args = ["session"]
            if self.today:
                args.append("today or utc_today()")
            if self.now:
                args.append("dt.datetime.now(dt.UTC)")
            return [
                call("value = await ", self.value_function, args, 4),
                "return StatValue(value=value)",
            ]
        lines: list[str] = []
        if self.today:
            lines.append("day = today or utc_today()")
        if self.now:
            lines.append("moment = dt.datetime.now(dt.UTC)")
        lines += self.statement_lines()
        if self.kind == "stat":
            lines.append("return StatValue(value=number(await session.scalar(statement)))")
        elif self.kind == "chart":
            lines.append("return chart_values(await session.execute(statement))")
        return lines

    def snapshot_lines(self) -> list[str]:
        """Return the body of the endpoint of a chart of snapshots: the stored values."""
        assert self.snapshot_of is not None
        dashboard, stat, days = self.snapshot_of
        conditions = (
            f"StatSnapshot.dashboard == {string(dashboard)}",
            f"StatSnapshot.widget == {string(stat)}",
            f"StatSnapshot.day > day - dt.timedelta(days={days})",
            "StatSnapshot.day <= day",
        )
        return [
            "day = today or utc_today()",
            "statement = select(StatSnapshot.day, StatSnapshot.value)",
            render(Call("statement.where", conditions), 4, "statement = "),
            "return chart_values(await session.execute(statement))",
        ]

    def statement_lines(self) -> list[str]:
        """Return the lines that build the statement of a stat or a chart, or that return the
        records of a list."""
        name = self.entity.name
        lines: list[str] = []
        if self.kind == "stat":
            lines += [f"value = {self.value}", f"statement = select(value).select_from({name})"]
        elif self.kind == "chart":
            lines += [
                render(self.key, 4, "key = "),
                f"value = {self.value}",
                f"statement = select(key, value).select_from({name}).group_by(key)",
            ]
        else:
            lines.append(f"statement = select({name})")
        for alias, (_, condition) in self.joins.items():
            lines.append(render(Call("statement.outerjoin", (alias, condition)), 4, "statement = "))
        for condition in self.where:
            lines.append(render(Call("statement.where", (condition,)), 4, "statement = "))
        if self.period is not None:
            column, datetime = self.period
            first = "day_start(start)" if datetime else "start"
            last = ("<", "day_start(end, 1)") if datetime else ("<=", "end")
            lines += [
                "if start is not None:",
                f"    statement = statement.where({column} >= {first})",
                "if end is not None:",
                f"    statement = statement.where({column} {last[0]} {last[1]})",
            ]
        if self.scoped:
            lines.append(f"statement = {self.entity.snake}_repository.owned(statement, scope)")
        if self.kind == "list":
            order = Call("statement.order_by", tuple(self.order))
            lines.append(render(order, 4, "statement = ", f".limit({self.limit})"))
            lines.append("records = await session.scalars(statement)")
            items = f"[{name}Read.model_validate(record) for record in records]"
            if self.hides:
                lines.append(f"items = {items}")
                lines.append(f"await {self.entity.snake}_repository.hide(session, items, scope)")
                lines.append("return items")
            else:
                lines.append(f"return {items}")
        return lines


@dataclass(slots=True)
class PyDashboard:
    """A dashboard with the endpoints of its widgets."""

    name: str
    id: str
    module: str
    """The module in the slice, for example `overview`."""
    path: str
    """The URL prefix of the dashboard, for example `/dashboards/overview`."""
    widgets: list[PyWidget]

    def code(self) -> str:
        lines = [line for w in self.widgets for line in w.body()]
        lines += [line for w in self.widgets if w.snapshots for line in w.value_lines()]
        return "\n".join(lines)

    @property
    def scoped(self) -> bool:
        """True if a widget reads the records of the scope of the request (`Scope`)."""
        return any(w.scoped or w.hides for w in self.widgets)

    def entities(self) -> list[PyEntity]:
        """The entities of the widgets, in the order of the widgets."""
        found: dict[str, PyEntity] = {}
        for w in self.widgets:
            found.setdefault(w.entity.name, w.entity)
        return list(found.values())

    def aliases(self) -> list[tuple[str, str]]:
        """The aliases of the joined entities: the name and the class."""
        found: dict[str, str] = {}
        for w in self.widgets:
            for alias, (cls, _) in w.joins.items():
                found.setdefault(alias, cls)
        return sorted(found.items())

    def imports(self, guard: str | None, module: str | None) -> str:
        """Return the import block of the module of the dashboard."""
        code = self.code()
        lines = {
            "from fastapi import APIRouter, Depends"
            if any(w.protected or w.scoped or w.hides for w in self.widgets)
            else "from fastapi import APIRouter",
            "from app.core.db import SessionDep, me"
            if any(w.me for w in self.widgets)
            else "from app.core.db import SessionDep",
            "from app.core.errors import problem_responses",
        }
        sql = {n for n in ("and_", "false", "not_", "or_", "select", "true") if f"{n}(" in code}
        sql |= {"func"} if "func." in code else set()
        lines.add(from_import("sqlalchemy", sql))
        if self.aliases():
            lines.add("from sqlalchemy.orm import aliased")
        if "dt." in code or any(w.snapshots and w.value_params()[1:] for w in self.widgets):
            lines.add("import datetime as dt")
        if any(w.snapshots for w in self.widgets):
            lines.add("from sqlalchemy.ext.asyncio import AsyncSession")
        if any(w.snapshot_of for w in self.widgets):
            lines.add("from app.core.snapshots import StatSnapshot")
        if "Decimal(" in code:
            lines.add("from decimal import Decimal")
        if "UUID(" in code:
            lines.add("from uuid import UUID")
        core: dict[str, set[str]] = {}
        if self.scoped:
            lines.add("from typing import Annotated")
            core.setdefault("access", set()).update({"RecordScope", "scope_of"})
        for e in {w.entity.slice: w.entity for w in self.widgets if w.scoped or w.hides}.values():
            lines.add(f"from app.features.{e.slice} import repository as {e.snake}_repository")
        if guard is not None and module is not None and any(w.protected for w in self.widgets):
            core.setdefault(module, set()).add(guard)
        for name, names in core.items():
            lines.add(from_import(f"app.core.{name}", names))
        if "day_start(" in code:
            lines.add("from app.core.pagination import day_start")
        helpers = {
            n for n in ("chart_values", "interval_of", "number", "utc_today") if f"{n}(" in code
        }
        if any(w.today for w in self.widgets):
            helpers.add("Today")
        if any(w.week for w in self.widgets):
            helpers.add("WeekStart")
        if any(w.period for w in self.widgets):
            helpers |= {"PeriodEnd", "PeriodStart"}
        if helpers:
            lines.add(from_import("app.features.dashboards.aggregates", helpers))
        schemas = {w.returns for w in self.widgets if w.kind != "list"}
        if schemas:
            lines.add(from_import("app.features.dashboards.schemas", schemas))
        for w in self.widgets:
            if w.kind == "list":
                lines.add(f"from app.features.{w.entity.slice}.schemas import {w.entity.name}Read")
        enums: dict[str, set[str]] = {}
        classes: set[str] = set()
        for w in self.widgets:
            for e in w.entity.app_entities.values():
                if e.name + "." in code or f"({e.name})" in code or f"[{e.name}" in code:
                    classes.add(e.name)
                for enum in (f.enum for f in e.fields if f.enum is not None):
                    if enum.name + "." in code:
                        enums.setdefault(e.slice, set()).add(enum.name)
        classes |= {cls for _, cls in self.aliases()}
        if classes:
            lines.add(from_import("app.models", classes))
        for slice_name, names in enums.items():
            lines.add(from_import(f"app.features.{slice_name}.enums", names))
        return import_block(lines)


def python_dashboards(
    definition: AppDefinition, entities: dict[str, PyEntity]
) -> dict[str, PyDashboard]:
    """Return the dashboards that have a stat, a chart, or a list widget, by name.

    Raise GenerationError if a name of the slice is taken, or if a widget
    reads a computed field, which has no column.
    """
    if definition.ui is None:
        return {}
    found: dict[str, PyDashboard] = {}
    for name, dashboard in definition.ui.dashboards.items():
        widgets = [
            _snapshot_chart(definition, entities, name, widget_name, widget)
            if isinstance(widget, ChartWidget) and widget.snapshots is not None
            else _widget(definition, entities, name, widget_name, widget)
            for widget_name, widget in dashboard.widgets.items()
            if isinstance(widget, StatWidget | ChartWidget | ListWidget)
        ]
        if widgets:
            module = snake(name)
            found[name] = PyDashboard(
                name, dashboard.id, module, f"{PREFIX}/{kebab(name)}", widgets
            )
    _check_names(definition, entities, found)
    return found


def _check_names(
    definition: AppDefinition, entities: dict[str, PyEntity], dashboards: dict[str, PyDashboard]
) -> None:
    if not dashboards:
        return
    for entity in entities.values():
        if entity.slice == SLICE or entity.path == PREFIX or entity.path.startswith(PREFIX + "/"):
            raise GenerationError(
                f"The entity '{entity.name}' has the slice or the URL prefix of the dashboards "
                f"({PREFIX}). Rename the entity, or give it another prefix with x-fastapi-path."
            )
    for dashboard in dashboards.values():
        if dashboard.module in _MODULES:
            raise GenerationError(
                f"The dashboard '{dashboard.name}' has the name of a module of the slice "
                f"'{SLICE}'. Give it another name."
            )
        for widget in dashboard.widgets:
            if widget.operation_id in definition.operations:
                raise GenerationError(
                    f"The endpoint of the widget '{widget.id}' has the operation ID "
                    f"'{widget.operation_id}' of an operation. Rename the widget or the operation."
                )


def _widget(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    dashboard: str,
    name: str,
    widget: StatWidget | ChartWidget | ListWidget,
) -> PyWidget:
    if isinstance(widget, ListWidget):
        assert definition.ui is not None
        view = definition.ui.views[widget.view]
        assert isinstance(view, TableView | CardsView)
        entity_name = view.entity
    else:
        assert widget.entity is not None
        entity_name = widget.entity
    result = _plain(definition, entities[entity_name], dashboard, name, widget)
    entity = result.entity
    result.scoped = result.protected and entity.scoped
    result.hides = result.protected and isinstance(widget, ListWidget) and bool(entity.hides)
    builder = FilterBuilder(definition, result)
    for path, condition in widget.filter.items():
        builder.filter(path, condition)
    if widget.period_field is not None:
        path = builder.resolve(widget.period_field)
        assert path.field is not None
        result.period = (builder.column(path), path.field.type == "datetime")
    if isinstance(widget, StatWidget | ChartWidget):
        result.aggregate = widget.aggregate
        result.value = builder.aggregate(widget.aggregate, widget.field)
    if isinstance(widget, StatWidget):
        result.snapshots = widget.snapshots is not None
    if isinstance(widget, ChartWidget):
        assert widget.group_by is not None
        result.key = builder.group(widget.group_by, widget.interval)
        result.week = isinstance(result.key, Call) and widget.interval == "week"
    if isinstance(widget, ListWidget):
        assert definition.ui is not None
        view = definition.ui.views[widget.view]
        assert isinstance(view, TableView | CardsView)
        sort = widget.sort or view.sort
        result.order = [*builder.order(sort), f"{entity.name}.id.asc()"]
        result.limit = widget.limit
    result.test = _Tests(definition, result, widget).plan()
    return result


def _plain(
    definition: AppDefinition,
    entity: PyEntity,
    dashboard: str,
    name: str,
    widget: StatWidget | ChartWidget | ListWidget,
) -> PyWidget:
    """Return a widget with its endpoint and the permission of the list operation of its
    entity, without its query."""
    lists = [op for op in entity.operations if op.kind == "list"]
    operation_id = f"{snake(dashboard)}_{snake(name)}"
    auth = definition.auth
    return PyWidget(
        name=name,
        id=widget.id,
        kind=widget.kind,
        label=widget.label or name.replace("_", " ").capitalize(),
        operation_id=operation_id,
        path="/" + kebab(name),
        entity=entity,
        permission=lists[0].name if lists else operation_id,
        protected=auth is not None and not (lists and lists[0].name in auth.public_operations),
    )


def _snapshot_chart(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    dashboard: str,
    name: str,
    widget: ChartWidget,
) -> PyWidget:
    """Return a chart of snapshots: its endpoint gives the stored values of its stat, with the
    permission of the stat (ADR 0042)."""
    assert definition.ui is not None and widget.snapshots is not None
    stat = definition.ui.dashboards[dashboard].widgets[widget.snapshots]
    assert isinstance(stat, StatWidget)
    result = _plain(definition, entities[stat.entity], dashboard, name, widget)
    result.today = True
    result.snapshot_of = (dashboard, widget.snapshots, widget.days)
    return result


class FilterTarget(Protocol):
    """A widget or a job: the joins and the conditions of its filter go into it."""

    id: str
    entity: PyEntity
    joins: dict[str, tuple[str, str]]
    """The aliases of the joined entities: the class and the join condition."""
    where: list[Expr]
    today: bool
    """True if a condition uses `day`, the date of `$today`."""
    me: bool
    """True if a condition uses `me()`, the signed-in user of `$me`."""
    now: bool
    """True if a condition uses `moment`, the time of `$now`."""


class FilterBuilder:
    """Builds the joins, the conditions, and the expressions of a widget or of a job.

    A condition of `$today` uses the variable `day`, and a condition of
    `$now` on a date-time field uses `moment`. The code of the widget or of
    the job sets them. A condition of `$me` uses `me()` of `app.core.db`:
    the signed-in user of the request.
    """

    def __init__(
        self,
        definition: AppDefinition,
        widget: FilterTarget,
        what: str = "widget",
        source: str | None = None,
    ) -> None:
        self.definition = definition
        self.widget = widget
        self.entity = widget.entity
        self.what = what
        self.source_name = source or widget.entity.name
        """The class or the alias of the entity in the conditions."""

    def resolve(self, path: str) -> PyPath:
        resolved = resolve_path(self.entity, path)
        if resolved.computed:
            raise GenerationError(
                f"The {self.what} '{self.widget.id}' reads the computed field '{path}'. The "
                f"FastAPI app reads the records of a {self.what} in the database, and a computed "
                "field has no column. Use a stored field."
            )
        return resolved

    def source(self, path: PyPath, hops: int | None = None) -> str:
        """Return the class or the alias of the entity after the hops of a path, with its joins."""
        source = self.source_name
        segments = path.path.split(".")
        for index, hop in enumerate(path.hops[:hops]):
            alias = "_" + "_".join([self.entity.snake, *segments[: index + 1]])
            relation = hop.relation
            if relation.side == "fk":
                condition = f"{alias}.id == {source}.{relation.fk_attr}"
            else:
                condition = f"{alias}.{relation.remote_fk} == {source}.id"
            self.widget.joins.setdefault(alias, (hop.target.name, condition))
            source = alias
        return source

    def column(self, path: PyPath) -> str:
        """Return the column of a path that ends in a field, an ID, or a relation to one record."""
        source = self.source(path)
        relation = path.relation
        if path.field is not None:
            return f"{source}.{path.field.attr}"
        if relation is None:
            return f"{source}.id"
        if relation.side == "fk":
            return f"{source}.{relation.fk_attr}"
        # A `one_to_one` relation without the foreign key: join the target.
        alias = "_" + "_".join([self.entity.snake, *path.path.split(".")])
        target = path.entity.target(relation)
        self.widget.joins.setdefault(
            alias, (target.name, f"{alias}.{relation.remote_fk} == {source}.id")
        )
        return f"{alias}.id"

    def filter(self, path_text: str, condition: JsonValue) -> None:
        path = self.resolve(path_text)
        conditions: dict[str, JsonValue] = (
            condition
            if isinstance(condition, dict)
            else {"in" if isinstance(condition, list) else "eq": condition}
        )
        for op, operand in conditions.items():
            self.widget.where.append(self.condition(path, op, operand))

    def condition(self, path: PyPath, op: str, operand: JsonValue) -> Expr:
        """Return the condition of one operator of the filter on a path."""
        relation = path.relation
        if relation is not None and relation.many:
            return self.many(path, op, operand)
        column = self.column(path)
        field_type = path.field.type if path.field is not None else "uuid"
        operands = operand if isinstance(operand, list) else [operand]
        if field_type == "datetime" and all(_is_day(o) for o in operands if o is not None):
            return self.by_day(column, op, [self.literal(path, o, day=True) for o in operands])
        if op in ("eq", "ne") and operand is None:
            return f"{column}.{'is_' if op == 'eq' else 'is_not'}(None)"
        if op in ("eq", "ne") and isinstance(operand, bool):
            return f"{column}.{'is_' if op == 'eq' else 'is_not'}({operand})"
        if op in ("eq", "ne"):
            value = self.literal(path, operand)
            if op == "eq":
                return f"{column} == {value}"
            if operand == ME:
                # Without a signed-in user, `$me` is null: all records pass.
                return Call("or_", (f"{column}.is_(None)", f"{column}.is_distinct_from({value})"))
            return Call("or_", (f"{column}.is_(None)", f"{column} != {value}"))
        if op in ("in", "not_in"):
            values = [self.literal(path, o) for o in operands if o is not None]
            listed = Call(
                f"{column}.in_" if op == "in" else f"{column}.not_in",
                ("[" + ", ".join(values) + "]",),
            )
            has_null = None in operands
            if op == "in":
                return Call("or_", (f"{column}.is_(None)", listed)) if has_null else listed
            return listed if has_null else Call("or_", (f"{column}.is_(None)", listed))
        if operand is None:
            return "false()"
        symbol = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[op]
        return f"{column} {symbol} {self.literal(path, operand)}"

    def by_day(self, column: str, op: str, days: list[str]) -> Expr:
        """Return a condition of a date-time column and dates: the days in UTC."""

        def on(day: str) -> Expr:
            return Call(
                "and_", (f"{column} >= day_start({day})", f"{column} < day_start({day}, 1)")
            )

        def off(day: str) -> Expr:
            return Call("or_", (f"{column} < day_start({day})", f"{column} >= day_start({day}, 1)"))

        day = days[0]
        match op:
            case "eq":
                return on(day)
            case "in":
                return on(day) if len(days) == 1 else Call("or_", tuple(on(d) for d in days))
            case "ne" | "not_in":
                offs = tuple(off(d) for d in days)
                return Call(
                    "or_",
                    (f"{column}.is_(None)", offs[0] if len(offs) == 1 else Call("and_", offs)),
                )
            case "lt":
                return f"{column} < day_start({day})"
            case "lte":
                return f"{column} < day_start({day}, 1)"
            case "gt":
                return f"{column} >= day_start({day}, 1)"
            case _:
                return f"{column} >= day_start({day})"

    def many(self, path: PyPath, op: str, operand: JsonValue) -> Expr:
        """Return a condition on the IDs of a relation to many records: one of them, or none."""
        relation = path.relation
        assert relation is not None
        source = self.source(path)
        target = path.entity.target(relation)
        operands = operand if isinstance(operand, list) else [operand]
        ids = [self.literal(path, o) for o in operands if o is not None]
        if op not in ("eq", "in", "ne", "not_in"):
            return "false()"
        if not ids:
            return "false()" if op in ("eq", "in") else "true()"
        inner = Call(f"{target.name}.id.in_", ("[" + ", ".join(ids) + "]",))
        has = Call(f"{source}.{relation.attr}.any", (inner,))
        return has if op in ("eq", "in") else Call("not_", (has,))

    def literal(self, path: PyPath, value: JsonValue, *, day: bool = False) -> str:
        """Return a value of the filter as a Python expression for the column of a path."""
        f = path.field
        if value == ME:
            self.widget.me = True
            return "me()"
        if value == "$today" or (value == "$now" and (day or (f is not None and f.type == "date"))):
            self.widget.today = True
            return "day"
        if value == "$now":
            self.widget.now = True
            return "moment"
        if f is None:
            return f'UUID("{value}")'
        match f.type:
            case "enum":
                assert f.enum is not None
                return f"{f.enum.name}.{constant(str(value))}"
            case "decimal":
                return f'Decimal("{value}")'
            case "date":
                return f'dt.date.fromisoformat("{value}")'
            case "datetime" if day:
                return f'dt.date.fromisoformat("{value}")'
            case "datetime":
                return f'dt.datetime.fromisoformat("{value}")'
            case "uuid":
                return f'UUID("{value}")'
            case "integer" | "boolean":
                return "True" if value is True else "False" if value is False else str(value)
            case _:
                return string(str(value))

    def aggregate(self, aggregate: str, path_text: str | None) -> str:
        if aggregate == "count" or path_text is None:
            return f"func.count({self.entity.name}.id)"
        column = self.column(self.resolve(path_text))
        if aggregate == "sum":
            return f"func.coalesce(func.sum({column}), 0)"
        return f"func.{aggregate}({column})"

    def group(self, path_text: str, interval: str = "month") -> Expr:
        """Return the group key of a chart: the column, or the interval of a date column."""
        path = self.resolve(path_text)
        column = self.column(path)
        f = path.field
        if f is None or f.type not in ("date", "datetime"):
            return column
        args = ["session", column, f'"{interval}"']
        if f.type == "datetime":
            # A date-time is in the interval of its day in UTC.
            args.append("utc=True")
        if interval == "week":
            args.append("week_start=week_start")
        return Call("interval_of", tuple(args))

    def order(self, sort: Sort | None) -> list[str]:
        if sort is None:
            return []
        path = self.resolve(sort.field)
        relation = path.relation
        if relation is not None and not relation.many:
            target = path.entity.target(relation)
            display = definition_display(self.definition.entities[target.name])
            path = self.resolve(f"{sort.field}.{display}") if relation.side == "fk" else path
        direction = "desc" if sort.direction == "desc" else "asc"
        return [f"{self.column(path)}.{direction}().nulls_last()"]


def _is_day(value: JsonValue) -> bool:
    """Return True for `$today`, and for a date without a time."""
    return value == "$today" or (isinstance(value, str) and len(value) == 10)


class FilterValues:
    """Finds the values of the fields of a test record that pass or fail a filter.

    `today` is the date of `$today` (and of `$now` on a date field) in the
    test. A value of `$now` on a date-time field is the days after the
    variable `now` of the test.
    """

    def __init__(self, definition: AppDefinition, entity: PyEntity, today: dt.date) -> None:
        self.definition = definition
        self.entity = entity
        self.fields = definition.entities[entity.name].fields
        self.today = today

    def direct_field(self, path_text: str) -> PyField | None:
        """Return the field of a path without hops whose type a test can give values, or None."""
        path = resolve_path(self.entity, path_text)
        f = path.field
        if path.hops or f is None or path.computed or f.type not in _TEST_TYPES:
            return None
        return f

    def values(
        self, f: PyField, conditions: dict[str, JsonValue]
    ) -> tuple[list[TestValue], list[TestValue]] | None:
        """Return the values of a field that pass the conditions, and the values that fail."""
        operands = [
            item
            for operand in conditions.values()
            for item in (operand if isinstance(operand, list) else [operand])
        ]
        if any(o is None for o in operands):
            return None
        candidates = self.candidates(f, operands)
        if candidates is None:
            return None
        passing: list[TestValue] = []
        failing: list[TestValue] = []
        for candidate in candidates:
            ok = all(
                passes(candidate.value, op, self.operand(f, operand))
                for op, operand in conditions.items()
            )
            (passing if ok else failing).append(candidate)
        return passing, failing

    def operand(self, f: PyField, operand: JsonValue) -> object:
        if isinstance(operand, list):
            return [self.operand(f, o) for o in operand]
        if operand == "$now":
            return 0 if f.type == "datetime" else self.today
        if operand == "$today":
            return self.today
        if f.type == "date" or (f.type == "datetime" and _is_day(operand)):
            return dt.date.fromisoformat(str(operand))
        if f.type == "datetime":
            return dt.datetime.fromisoformat(str(operand))
        if f.type == "decimal":
            return Decimal(str(operand))
        return operand

    def candidates(self, f: PyField, operands: list[JsonValue]) -> list[TestValue] | None:
        """Return the values to try for a field: the operands, and the values around them."""
        dsl = self.fields[f.name]
        match f.type:
            case "enum":
                assert f.enum is not None
                return [TestValue(f"{f.enum.name}.{name}", value) for name, value in f.enum.members]
            case "boolean":
                return [TestValue("True", True), TestValue("False", False)]
            case "integer" | "decimal":
                numbers = sorted({Decimal(str(o)) + step for o in operands for step in _STEPS})
                found = [n for n in numbers if _in_range(dsl, n)]
                if f.type == "integer":
                    return [TestValue(str(int(n)), int(n)) for n in found if n == int(n)]
                return [TestValue(f'Decimal("{n}")', n) for n in found]
            case "date":
                days = sorted(
                    {self.day(o) + dt.timedelta(days=s) for o in operands for s in _STEPS}
                )
                return [TestValue(_date_code(d), d) for d in days]
            case _:
                if all(o == "$now" for o in operands):
                    steps = [s for s in _STEPS if s != 0]
                    return [TestValue(f"now + dt.timedelta(days={s})", s) for s in steps]
                if all(_is_day(o) for o in operands):
                    days = sorted(
                        {self.day(o) + dt.timedelta(days=s) for o in operands for s in _STEPS}
                    )
                    return [TestValue(_datetime_code(d), d) for d in days]
                return None

    def day(self, operand: JsonValue) -> dt.date:
        return self.today if operand in ("$today", "$now") else dt.date.fromisoformat(str(operand))


class _Tests(FilterValues):
    """Plans the records of the generated test of a widget, or None if it cannot."""

    def __init__(
        self,
        definition: AppDefinition,
        widget: PyWidget,
        source: StatWidget | ChartWidget | ListWidget,
    ) -> None:
        super().__init__(definition, widget.entity, TEST_TODAY)
        self.widget = widget
        self.source = source

    def plan(self) -> WidgetTest | None:
        paths: dict[str, list[TestValue]] = {}
        failing: dict[str, list[TestValue]] = {}
        now = False
        record_filter = dict(self.source.filter)
        period = self.source.period_field
        if period is not None:
            # The test sends the period: the records of the period pass, and the others fail.
            if period in record_filter:
                return None
            first, last = (day.isoformat() for day in TEST_PERIOD)
            record_filter[period] = {"gte": first, "lte": last}
        for path_text, condition in record_filter.items():
            f = self.direct_field(path_text)
            if f is None:
                return None
            conditions: dict[str, JsonValue] = (
                condition
                if isinstance(condition, dict)
                else {"in" if isinstance(condition, list) else "eq": condition}
            )
            found = self.values(f, conditions)
            if found is None:
                return None
            passing, fails = found
            if not passing or not fails:
                return None
            # A record before the period, and a record after it.
            ends = [fails[0], fails[-1]] if path_text == period and len(fails) > 1 else fails[:1]
            paths[f.attr], failing[f.attr] = passing, ends
            now = now or "now" in passing[0].code
        count = 3
        records: list[dict[str, str]] = []
        for index in range(count):
            records.append(
                {attr: values[index % len(values)].code for attr, values in paths.items()}
            )
        for attr, fails in failing.items():
            for fail in fails:
                record = {a: values[0].code for a, values in paths.items()}
                record[attr] = fail.code
                records.append(record)
        test = WidgetTest(records, count, [], now=now)
        filled = self.fill(test, paths)
        if not filled or not self.unique_ok(test):
            return None
        return test

    def fill(self, test: WidgetTest, paths: dict[str, list[TestValue]]) -> bool:
        """Give the passing records the values of the aggregate, the group, or the sort.

        Set the expected result. Return False if the test cannot know it.
        """
        passing = test.records[: test.passing]
        numbers: list[Decimal] = [Decimal(1)] * test.passing
        source = self.source
        if isinstance(source, StatWidget | ChartWidget) and source.aggregate != "count":
            assert source.field is not None
            f = self.direct_field(source.field)
            if f is None or f.type not in _NUMBER_TYPES or f.attr in paths:
                return False
            dsl = self.fields[f.name]
            low = Decimal(str(dsl.min)) if dsl.min is not None else Decimal(0)
            numbers = [low + 1 + index for index in range(test.passing)]
            if not all(_in_range(dsl, n) for n in numbers):
                return False
            for record, n in zip(passing, numbers, strict=True):
                record[f.attr] = str(int(n)) if f.type == "integer" else f'Decimal("{n}")'
        if isinstance(source, StatWidget):
            value = _number(_aggregate(source.aggregate, numbers))
            test.checks = [f'assert response.json() == {{"value": {value}}}']
            return True
        if isinstance(source, ChartWidget):
            return self.fill_chart(test, source, numbers, paths)
        return self.fill_list(test, paths)

    def fill_chart(
        self,
        test: WidgetTest,
        source: ChartWidget,
        numbers: list[Decimal],
        paths: dict[str, list[TestValue]],
    ) -> bool:
        group_by = source.group_by
        assert group_by is not None
        path = resolve_path(self.entity, group_by)
        passing = test.records[: test.passing]
        # The first record is in the first group, the next two in the second.
        groups = [0, 1, 1]
        relation = path.relation
        if relation is not None:
            if path.hops or relation.side != "fk" or relation.many:
                return False
            assert relation.fk_attr is not None
            test.parents = (path.entity.target(relation), relation.fk_attr, 2)
            for record, group in zip(passing, groups, strict=True):
                record[relation.fk_attr] = f"parents[{group}].id"
            sums = [_aggregate(source.aggregate, _of(numbers, groups, g)) for g in (0, 1)]
            values = [f"(str(parents[{g}].id), {_number(sums[g])})" for g in (0, 1)]
            test.checks = [
                f"expected = sorted([{', '.join(values)}])",
                'groups = [{"key": key, "value": value} for key, value in expected]',
                'assert response.json() == {"groups": groups}',
            ]
            return True
        f = self.direct_field(group_by)
        if f is None or f.attr in paths:
            return False
        if f.type == "enum":
            assert f.enum is not None
            members = f.enum.members[:2] if len(f.enum.members) > 1 else f.enum.members * 2
            keys = [value for _, value in members]
            codes = [f"{f.enum.name}.{name}" for name, _ in members]
        elif f.type in ("date", "datetime"):
            # A Thursday and a Sunday of two years: two groups of each interval.
            days = [dt.date(2025, 1, 16), dt.date(2026, 2, 15)]
            keys = [_interval_key(d, source.interval) for d in days]
            make = _date_code if f.type == "date" else _datetime_code
            codes = [make(d) for d in days]
        else:
            return False
        for record, group in zip(passing, groups, strict=True):
            record[f.attr] = codes[group]
        totals: dict[str, list[Decimal]] = {}
        for group, n in zip(groups, numbers, strict=True):
            totals.setdefault(keys[group], []).append(n)
        items = [
            f'    {{"key": "{key}", "value": {_number(_aggregate(source.aggregate, values))}}},'
            for key, values in sorted(totals.items())
        ]
        test.checks = ["groups = [", *items, "]", 'assert response.json() == {"groups": groups}']
        return True

    def fill_list(self, test: WidgetTest, paths: dict[str, list[TestValue]]) -> bool:
        source = self.source
        assert isinstance(source, ListWidget)
        assert self.definition.ui is not None
        view = self.definition.ui.views[source.view]
        assert isinstance(view, TableView | CardsView)
        sort = source.sort or view.sort
        limit = min(source.limit, test.passing)
        if sort is None:
            ids = f"sorted(str(r.id) for r in records[:{test.passing}])"
            ids += f"[:{limit}]" if limit < test.passing else ""
            test.checks = [f"ids = {ids}", _LIST_CHECK]
            return True
        f = self.direct_field(sort.field)
        if f is None or f.type not in _TEST_TYPES - {"boolean", "enum"}:
            return False
        values = paths.get(f.attr)
        if values is None:
            dsl = self.fields[f.name]
            candidates = self.candidates(f, [self.example(f, dsl)])
            if candidates is None:
                return False
            values = candidates
        if len(values) < test.passing:
            return False
        # The values are in ascending order. The records get them in descending
        # order, so that the order of the endpoint is not the order of the records.
        count = test.passing
        for index, record in enumerate(test.records[:count]):
            record[f.attr] = values[count - 1 - index].code
        order = range(count) if sort.direction == "desc" else range(count - 1, -1, -1)
        indexes = tuple(order)[:limit]
        test.checks = [f"ids = [str(records[i].id) for i in {indexes!r}]", _LIST_CHECK]
        return True

    def example(self, f: PyField, dsl: DslField) -> JsonValue:
        """Return an operand for the values of a sort field without a filter."""
        if f.type == "date":
            return TEST_TODAY.isoformat()
        if f.type == "datetime":
            return TEST_TODAY.isoformat()
        low = dsl.min if dsl.min is not None else 0
        return low + 4

    def unique_ok(self, test: WidgetTest) -> bool:
        """Return False if the test can give two records the same value of a unique column.

        A test does not set a column of a unique rule of many columns, and gives
        each record its own value of a unique field.
        """
        columns = {c for r in self.entity.unique_rules for c in r.columns}
        for f in self.entity.fields:
            codes = [r[f.attr] for r in test.records if f.attr in r]
            if codes and (f.name in columns or (f.unique and len(codes) != len(set(codes)))):
                return False
        return True


def passes(value: object, op: str, operand: object) -> bool:
    """Return True if a test value passes an operator of the filter.

    The values have no empty value, so that the operators are the plain
    comparisons. A date-time value of a test is its day (a date), or the
    days after now (an integer) for `$now`.
    """
    if isinstance(operand, list):
        hit = any(value == o for o in cast(list[object], operand))
        return hit if op in ("eq", "in") else not hit
    # The values of one field have one type: a date, a number, a text, or a boolean.
    a: Any = value
    b: Any = operand
    match op:
        case "eq" | "in":
            return a == b
        case "ne" | "not_in":
            return a != b
        case "lt":
            return bool(a < b)
        case "lte":
            return bool(a <= b)
        case "gt":
            return bool(a > b)
        case _:
            return bool(a >= b)


def _in_range(f: DslField, value: Decimal) -> bool:
    """Return True if a number is in the range of a field."""
    low = f.min if f.min is not None else None
    high = f.max if f.max is not None else None
    return (low is None or value >= Decimal(str(low))) and (
        high is None or value <= Decimal(str(high))
    )


def _interval_key(day: dt.date, interval: str) -> str:
    """Return the key of the interval of a day, as the endpoint gives it (weeks from Monday)."""
    if interval == "week":
        return (day - dt.timedelta(days=day.weekday())).isoformat()
    return day.isoformat()[: {"day": 10, "month": 7, "year": 4}[interval]]


def _date_code(day: dt.date) -> str:
    return f"dt.date({day.year}, {day.month}, {day.day})"


def _datetime_code(day: dt.date) -> str:
    """Return a date-time at noon in UTC of a day, as Python code."""
    return f"dt.datetime({day.year}, {day.month}, {day.day}, 12, tzinfo=dt.UTC)"


def _aggregate(aggregate: str, numbers: list[Decimal]) -> Decimal | None:
    """Return an aggregate of the numbers of a test, as the endpoint computes it."""
    if aggregate == "count":
        return Decimal(len(numbers))
    if not numbers:
        return Decimal(0) if aggregate == "sum" else None
    match aggregate:
        case "sum":
            return sum(numbers, Decimal(0))
        case "avg":
            return sum(numbers, Decimal(0)) / len(numbers)
        case "min":
            return min(numbers)
        case _:
            return max(numbers)


def _number(value: Decimal | None) -> str:
    """Return a number of a JSON response as a Python literal: the endpoints give floats."""
    return "None" if value is None else repr(float(value))


def _of(numbers: list[Decimal], groups: list[int], group: int) -> list[Decimal]:
    """Return the numbers of the records of one group."""
    return [n for n, g in zip(numbers, groups, strict=True) if g == group]
