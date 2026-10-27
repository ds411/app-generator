"""The dashboards of the front-end apps: stat tiles, charts, and record lists (ADR 0003).

The shared UI templates in `templates/ui/dashboards/` render the values of
this module. With mock data, a dashboard reads all records of the
entities that its widgets show, and filters, groups, and aggregates them
in the browser. With the API client (`ViewContext.widgets`), a dashboard
calls the endpoint of each widget: the API gives the value of a stat, the
groups of a chart, and the records of a list, and the dashboard loads the
related records of these by ID. Each widget has a function of the
dashboard data (`data`), with the same TypeScript values as the list
views (`appgen.bindings.shared.views`).
"""

from dataclasses import dataclass, field

from pydantic import JsonValue

from appgen.bindings.shared.gaps import GapSpec, component_gap
from appgen.bindings.shared.i18n import text_js
from appgen.bindings.shared.ui import css_var, js
from appgen.bindings.shared.views import (
    CardPlan,
    ColumnPlan,
    RelatedStep,
    Value,
    ViewContext,
    WidgetEndpoint,
    grid_classes,
    label,
    state_ids,
)
from appgen.dsl.auth import ME, has_me
from appgen.dsl.model import AppDefinition, Field
from appgen.dsl.ui.common import Grid, States
from appgen.dsl.ui.dashboards import (
    ChartWidget,
    CustomWidget,
    Dashboard,
    ListWidget,
    RecordFilter,
    StatWidget,
    currency_path,
    single_value,
)
from appgen.dsl.ui.fields import resolve_path
from appgen.dsl.ui.states import BUILT_IN_STATES
from appgen.dsl.ui.views import CardsView, Sort, TableView
from appgen.gen.naming import camel, constant, pascal

DEFAULT_COLUMNS = 4
"""The grid columns of a dashboard without a grid."""
_DEFAULT_RESPONSIVE = {"lg": 2, "sm": 1}
"""The grid columns below each breakpoint, for a dashboard without a grid."""


@dataclass(slots=True)
class WidgetPlan:
    """A widget of a dashboard, with the TypeScript that gives its data."""

    name: str
    element_id: str
    kind: str
    label: str
    classes: str
    """The Tailwind CSS classes of the grid cell: the column span."""
    function: str | None = None
    """The function of the dashboard data that gives the value, the chart data, or the rows."""
    body: list[str] = field(default_factory=list[str])
    """The lines of the function body."""
    returns: str = "number | null"
    format: str = "number"
    currency: str | None = None
    """The ISO 4217 code of a `currency` stat, or None for the default currency."""
    icon: str | None = None
    color: str | None = None
    href: str | None = None
    """The TypeScript path of the page that the widget opens, or None."""
    chart: str | None = None
    value_label: str = "Records"
    view: str | None = None
    """The list view of a list widget."""
    columns: list[ColumnPlan] = field(default_factory=list[ColumnPlan])
    card: CardPlan | None = None
    sort_id: str | None = None
    gap: GapSpec | None = None
    endpoint: WidgetEndpoint | None = None
    """With the API client: the endpoint that gives the value of the widget."""
    data: str | None = None
    """With the API client: the TypeScript type of the response in the dashboard data."""
    related: list[list[RelatedStep]] = field(default_factory=list[list[RelatedStep]])
    """With the API client: the related records of the records of a list, in stages."""
    target: str | None = None
    """With the API client: the entity of the groups of a chart of a relation."""
    groups: str | None = None
    """The TypeScript of the known groups of a chart, in their order, or None."""
    interval: str | None = None
    """The interval of the groups of a chart of dates, for example `week`, or None."""
    takes_period: bool = False
    """True if the function of the widget takes the period: the widget filters its records by
    the period field in the browser."""
    takes_me: bool = False
    """True if the function of the widget takes `me`, the ID of the signed-in user: the filter
    has `$me`."""
    change: str | None = None
    """The TypeScript of the change of a stat from the previous period (`compare`), or None."""
    store: str | None = None
    """With the API client: the store of the records of a list widget, for example `taskApi`."""

    @property
    def related_name(self) -> str:
        """The name of the constant with the related records of a list widget."""
        return f"{constant(self.name)}_RELATED"


@dataclass(slots=True)
class DashboardPlan:
    """The values of a dashboard that its template needs."""

    name: str
    dashboard: Dashboard
    motion: str = "full"
    """The motion setting of `ui.tokens.motion`: `full`, `reduced`, or `none`."""
    entities: list[str] = field(default_factory=list[str])
    """The entities that the dashboard reads, sorted by name."""
    grid: str = ""
    """The Tailwind CSS classes of the grid."""
    widgets: list[WidgetPlan] = field(default_factory=list[WidgetPlan])
    states: States = field(default_factory=lambda: BUILT_IN_STATES)
    state_ids: list[str] = field(default_factory=list[str])
    uses: set[str] = field(default_factory=set[str])
    icons: set[str] = field(default_factory=set[str])
    imports: list[str] = field(default_factory=list[str])
    server: bool = False
    """True if the widgets call the endpoints of the API client."""
    lookups: list[str] = field(default_factory=list[str])
    """With the API client: the related entities that the widgets show, sorted by name."""
    types: list[str] = field(default_factory=list[str])
    """With the API client: the entities whose types the code names, sorted by name."""

    @property
    def compare(self) -> bool:
        """True if a stat widget shows the change from the previous period."""
        return any(w.change for w in self.widgets)

    def code(self) -> str:
        """Return the TypeScript of the widgets, to find the helpers that they call."""
        parts: list[str] = []
        for widget in self.widgets:
            parts += [*widget.body, widget.href or "", widget.change or ""]
            parts += [c.cell for c in widget.columns]
            card = widget.card
            if card is not None:
                parts += [card.title, card.href or "", card.subtitle or "", card.badge or ""]
        return " ".join(parts)

    def needs(self, name: str) -> bool:
        """Return True if the code of the dashboard uses a name, for example `pageHref(`."""
        return name in self.code()

    def action(self, name: str | None) -> None:
        """Return None: a dashboard has no actions for its states."""
        return None

    def render_code(self) -> str:
        """Return the JSX code of the list widgets, which the component renders."""
        parts: list[str] = []
        for widget in self.widgets:
            parts += [c.cell for c in widget.columns]
            card = widget.card
            if card is not None:
                parts += [card.title, card.subtitle or "", card.badge or ""]
                parts += ["<Link"] if card.href else []
        return " ".join(parts)


def span_classes(grid: Grid | None, span: int) -> str:
    """Return the column span classes of a widget, with the responsive grid columns."""
    columns = grid.columns if grid else DEFAULT_COLUMNS
    responsive = (
        {bp: o.columns for bp, o in grid.responsive.items() if o.columns}
        if grid
        else _DEFAULT_RESPONSIVE
    )
    classes = [f"col-span-{min(span, columns)}"]
    for breakpoint, count in responsive.items():
        if count < span:
            classes.append(f"max-{breakpoint}:col-span-{count}")
    return " ".join(classes)


def build_dashboard(ctx: ViewContext, name: str) -> DashboardPlan:
    """Return the plan of a dashboard."""
    definition = ctx.definition
    assert definition.ui is not None
    dashboard = definition.ui.dashboards[name]
    plan = DashboardPlan(name=name, dashboard=dashboard)
    tokens = ctx.definition.ui.tokens if ctx.definition.ui else None
    if tokens is not None and tokens.motion is not None:
        plan.motion = tokens.motion.value
    grid = dashboard.grid
    if grid is None:
        plan.grid = "grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1"
    else:
        plan.grid = grid_classes(grid)
    entities: set[str] = set()
    # With the API client: the entities whose stores the dashboard uses.
    served: set[str] = set()
    for widget_name, widget in dashboard.widgets.items():
        classes = span_classes(grid, widget.span)
        widget_label = widget.label or label(widget_name)
        result = WidgetPlan(
            name=widget_name,
            element_id=widget.id,
            kind=widget.kind,
            label=widget_label,
            classes=classes,
            function=camel(widget_name),
        )
        if isinstance(widget, StatWidget):
            _stat(ctx, plan, result, widget, entities)
        elif isinstance(widget, ChartWidget):
            _chart(ctx, plan, result, widget, entities)
        elif isinstance(widget, ListWidget):
            _list(ctx, plan, result, widget, entities)
        else:
            assert isinstance(widget, CustomWidget)
            result.function = None
            result.gap = component_gap(definition, widget.id)
        if widget.id in ctx.widgets and not isinstance(widget, CustomWidget):
            plan.server = True
            _server(ctx, result, widget, served)
        plan.widgets.append(result)
    plan.entities = sorted(served if plan.server else entities)
    if plan.server:
        found = {s.entity for w in plan.widgets for stage in w.related for s in stage}
        found |= {w.target for w in plan.widgets if w.target}
        plan.lookups = sorted(found)
        lists = {_list_view(definition, w.view).entity for w in plan.widgets if w.view}
        plan.types = sorted(found | lists)
    defaults = definition.ui.defaults
    found = [s for s in (defaults.states if defaults else None, BUILT_IN_STATES) if s is not None]
    plan.states = States(
        loading=next(s.loading for s in found if s.loading is not None),
        empty=next(s.empty for s in found if s.empty is not None),
        error=next(s.error for s in found if s.error is not None),
    )
    plan.state_ids = state_ids(definition, None)
    error = plan.states.error
    if error and error.icon:
        plan.icons.add(error.icon)
    plan.imports = sorted(
        f'import {{ {w.gap.name} }} from "{w.gap.module}.gen";' for w in plan.widgets if w.gap
    )
    return plan


def _read(ctx: ViewContext, entity: str, paths: list[str], entities: set[str]) -> None:
    entities.add(entity)
    entities.update(ctx.lookups_of(entity, paths))


def _rows(
    ctx: ViewContext,
    entity: str,
    record_filter: RecordFilter,
    entities: set[str],
    period_field: str | None = None,
) -> list[str]:
    """Return the lines that set `rows` to the records of an entity that pass a filter, and
    whose period field is in the period of the dashboard."""
    _read(ctx, entity, [*record_filter, *([period_field] if period_field else [])], entities)
    source = f"data.records.{camel(entity)}"
    tests = [
        test
        for path, condition in record_filter.items()
        for test in _tests(ctx.value(entity, path), condition)
    ]
    if period_field is not None:
        tests.append(f"inPeriod({ctx.value(entity, period_field).expr}, period)")
    if not tests:
        return [f"const rows = {source};"]
    return [f"const rows = {source}.filter((row) => {' && '.join(tests)});"]


def _tests(value: Value, condition: JsonValue) -> list[str]:
    """Return the TypeScript tests of a filter condition.

    The condition is a value (equal to), a list of values (one of them), or
    a mapping of operators.
    """
    if isinstance(condition, dict):
        key = value.key_expr
        return [f'matchesOp({key}, "{op}", {_operand(v)})' for op, v in condition.items()]
    op = "in" if isinstance(condition, list) else "eq"
    return [f'matchesOp({value.key_expr}, "{op}", {_operand(condition)})']


def _operand(value: JsonValue) -> str:
    if value == ME:
        # Without a signed-in user, `$me` is a value that no record has, as null in SQL.
        return 'me ?? ""'
    if isinstance(value, list) and has_me(value):
        return "[" + ", ".join(_operand(item) for item in value) + "]"
    if value == "$today":
        return "today()"
    if value == "$now":
        return "new Date().toISOString()"
    return js(value)


def _aggregate(ctx: ViewContext, entity: str, aggregate: str, path: str | None, rows: str) -> str:
    if aggregate == "count" or path is None:
        return f"{rows}.length"
    value = ctx.value(entity, path)
    return f'aggregate({rows}.map((row) => {value.expr}), "{aggregate}")'


def _stat(
    ctx: ViewContext,
    plan: DashboardPlan,
    result: WidgetPlan,
    widget: StatWidget,
    entities: set[str],
) -> None:
    result.body = _rows(ctx, widget.entity, widget.filter, entities, widget.period_field)
    result.takes_period = widget.period_field is not None
    result.takes_me = has_me(widget.filter)
    if widget.compare:
        fn, me = result.function, ", me" if result.takes_me else ""
        result.change = f"change({fn}(data, period{me}), previous && {fn}(data, previous{me}))"
    if widget.field:
        _read(ctx, widget.entity, [widget.field], entities)
    result.body.append(
        f"return {_aggregate(ctx, widget.entity, widget.aggregate, widget.field, 'rows')};"
    )
    result.format = widget.format or _field_format(ctx, widget) or "number"
    if result.format == "currency":
        result.currency = _field_currency(ctx, widget)
    result.icon = widget.icon
    result.color = css_var(widget.color) if widget.color else None
    if widget.icon:
        plan.icons.add(widget.icon)
    if widget.link:
        result.href = ctx.href(widget.entity, widget.link, {}, "row")
    plan.uses.add("stat")


def _field_format(ctx: ViewContext, widget: StatWidget) -> str | None:
    """Return the number format of the field of an aggregate, or None."""
    if widget.aggregate == "count" or widget.field is None:
        return None
    member = resolve_path(ctx.definition, widget.entity, widget.field).member
    fmt = member.format if isinstance(member, Field) else None
    return fmt if fmt in ("number", "currency", "percent") else None


def _field_currency(ctx: ViewContext, widget: StatWidget) -> str | None:
    """Return the currency of the field of an aggregate, or None.

    For a field with the currency of each record (`currency_field`), the
    filter of the widget allows one currency (the validator checks it).
    """
    if widget.aggregate == "count" or widget.field is None:
        return None
    member = resolve_path(ctx.definition, widget.entity, widget.field).member
    if not isinstance(member, Field):
        return None
    if member.currency_field is not None:
        path = currency_path(widget.field, member.currency_field)
        code = single_value(widget.filter, path)
        return code.upper() if code else member.currency
    return member.currency


def _chart(
    ctx: ViewContext,
    plan: DashboardPlan,
    result: WidgetPlan,
    widget: ChartWidget,
    entities: set[str],
) -> None:
    entity = widget.entity
    result.body = _rows(ctx, entity, widget.filter, entities, widget.period_field)
    result.takes_period = widget.period_field is not None
    result.takes_me = has_me(widget.filter)
    _read(ctx, entity, [widget.group_by, *([widget.field] if widget.field else [])], entities)
    group = ctx.value(entity, widget.group_by)
    total = _aggregate(ctx, entity, widget.aggregate, widget.field, "group")
    if widget.aggregate != "count":
        total += " ?? 0"
    if group.kind == "one":
        key = f"(row) => {group.key_expr}"
        target = group.target or ""
        display = ctx.display_field(target)
        groups = (
            f"[...lookups.{camel(target)}.values()].map((item) => "
            f'({{ key: item.id, label: String(item.{display} ?? "") }}))'
        )
    elif group.type in ("date", "datetime"):
        # Each interval from the first to the last date, also without records.
        result.interval = widget.interval
        result.body.append(
            f"return intervalRows(rows, (row) => {group.expr}, (group) => {total}, "
            f'"{widget.interval}");'
        )
        _chart_labels(ctx, result, widget)
        plan.uses.update({"chart", "dates"})
        return
    else:
        # An enum: the definition check allows no other field type for a group.
        key = f"(row) => {group.expr} ?? null"
        badge = ctx.badge_sets.get(widget.badge or "") if widget.badge else None
        if badge is None and group.badge:
            badge = next((s for n, s in ctx.badge_sets.items() if camel(n) == group.badge), None)
        items: list[str] = []
        for enum_value in group.enum_values:
            style = badge.values.get(enum_value) if badge else None
            text = (style.label if style else None) or label(enum_value)
            item = f"{{ key: {js(enum_value)}, label: {text_js(text)}"
            if style and style.color:
                item += f", color: {js(css_var(style.color))}"
            items.append(item + " }")
        groups = "[" + ", ".join(items) + "]"
    args = f"rows, {key}, (group) => {total}"
    result.groups = groups
    if groups:
        args += f", {groups}"
    result.body.append(f"return groupRows({args});")
    _chart_labels(ctx, result, widget)
    plan.uses.add("chart")


def _chart_labels(ctx: ViewContext, result: WidgetPlan, widget: ChartWidget) -> None:
    """Set the kind of the chart, its data type, and the label of its values."""
    result.returns = "ChartDatum[]"
    result.chart = widget.chart
    entity_def = ctx.definition.entities[widget.entity]
    result.value_label = (
        entity_def.plural_label or label(widget.entity) + "s"
        if widget.aggregate == "count"
        else ctx.value(widget.entity, widget.field or "").label
    )


def _list(
    ctx: ViewContext,
    plan: DashboardPlan,
    result: WidgetPlan,
    widget: ListWidget,
    entities: set[str],
) -> None:
    view = _list_view(ctx.definition, widget.view)
    entity = view.entity
    view_plan = ctx.view_plan(widget.view)
    entities.add(entity)
    entities.update(view_plan.lookups)
    result.view = widget.view
    result.body = _rows(ctx, entity, widget.filter, entities, widget.period_field)
    result.takes_period = widget.period_field is not None
    result.takes_me = has_me(widget.filter)
    sort: Sort | None = widget.sort or view.sort
    if sort is not None:
        _read(ctx, entity, [sort.field], entities)
        value = ctx.value(entity, sort.field)
        desc = ", true" if sort.direction == "desc" else ""
        rows = f"sortBy(rows, (row) => {value.sort_expr}{desc})"
    else:
        rows = "sortBy(rows, (row) => row.id)"
    result.sort_id = widget.sort.id if widget.sort else None
    result.body.append(f"return {rows}.slice(0, {widget.limit});")
    result.returns = f"{pascal(entity)}[]"
    if isinstance(view, TableView):
        result.columns = view_plan.columns
        plan.uses.add("table")
    else:
        result.card = view_plan.card
    if widget.link:
        result.href = ctx.href(entity, widget.link, {}, "row")
    plan.uses.add("list")


def _server(
    ctx: ViewContext,
    result: WidgetPlan,
    widget: StatWidget | ChartWidget | ListWidget,
    entities: set[str],
) -> None:
    """Make a widget read its value from its endpoint: the dashboard data has the response.

    A chart keeps its known groups: a chart of a relation shows the related
    records of the groups of the API, which the dashboard loads by ID. A
    list loads the related records of its records by ID.
    """
    result.endpoint = ctx.widgets[widget.id]
    # The API gives the values of the period and of the signed-in user: the function does not
    # take them.
    result.takes_period = False
    result.takes_me = False
    data = f"data.{result.function}"
    if isinstance(widget, StatWidget | ChartWidget):
        # The dashboard loads again after a change of the records.
        entities.add(widget.entity)
    if isinstance(widget, StatWidget):
        result.data = "number | null"
        result.body = [f"return {data};"]
        if widget.compare:
            result.change = f"change({result.function}(data), {data}Previous)"
        return
    if isinstance(widget, ListWidget):
        view = _list_view(ctx.definition, widget.view)
        result.data = result.returns
        result.store = f"{camel(view.entity)}Api"
        result.related = ctx.view_plan(widget.view).related
        entities.add(view.entity)
        entities.update(s.entity for stage in result.related for s in stage)
        result.body = [f"return {data};"]
        return
    result.data = "ChartValue[]"
    group = ctx.value(widget.entity, widget.group_by)
    groups = f", {result.groups}" if result.groups else ""
    if group.kind == "one":
        # The known groups are the related records of the groups of the API.
        target = group.target or ""
        result.target = target
        entities.add(target)
        label = f'(item) => String(item.{ctx.display_field(target)} ?? "")'
        groups = f", recordGroups({data}, lookups.{camel(target)}, {label})"
    if result.interval is not None:
        result.body = [f'return chartIntervals({data}, "{result.interval}");']
        return
    result.body = [f"return chartGroups({data}{groups});"]


def _list_view(definition: AppDefinition, name: str) -> TableView | CardsView:
    """Return the view of a list widget: the validator allows only a table or a card list."""
    assert definition.ui is not None
    view = definition.ui.views[name]
    assert isinstance(view, TableView | CardsView)
    return view
