"""The dashboards of the front-end apps: stat tiles, charts, and record lists (ADR 0003).

The shared UI templates in `templates/ui/dashboards/` render the values of
this module. A dashboard reads all records of the entities that its
widgets show, and filters, groups, and aggregates them in the browser.
Each widget has a function of the dashboard data (`data`), with the same
TypeScript values as the list views (`appgen.bindings.shared.views`).
"""

from dataclasses import dataclass, field

from pydantic import JsonValue

from appgen.bindings.shared.gaps import GapSpec, component_gap
from appgen.bindings.shared.ui import css_var, js
from appgen.bindings.shared.views import (
    CardPlan,
    ColumnPlan,
    Value,
    ViewContext,
    grid_classes,
    label,
    state_ids,
)
from appgen.dsl.ui.common import Grid, States
from appgen.dsl.ui.dashboards import (
    ChartWidget,
    CustomWidget,
    Dashboard,
    ListWidget,
    RecordFilter,
    StatWidget,
)
from appgen.dsl.ui.states import BUILT_IN_STATES
from appgen.dsl.ui.views import CardsView, Sort, TableView
from appgen.gen.naming import camel, pascal

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


@dataclass(slots=True)
class DashboardPlan:
    """The values of a dashboard that its template needs."""

    name: str
    dashboard: Dashboard
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

    def code(self) -> str:
        """Return the TypeScript of the widgets, to find the helpers that they call."""
        parts: list[str] = []
        for widget in self.widgets:
            parts += [*widget.body, widget.href or ""]
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
    grid = dashboard.grid
    if grid is None:
        plan.grid = "grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1"
    else:
        plan.grid = grid_classes(grid)
    entities: set[str] = set()
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
        plan.widgets.append(result)
    plan.entities = sorted(entities)
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
    ctx: ViewContext, entity: str, record_filter: RecordFilter, entities: set[str]
) -> list[str]:
    """Return the lines that set `rows` to the records of an entity that pass a filter."""
    _read(ctx, entity, list(record_filter), entities)
    source = f"data.records.{camel(entity)}"
    tests = [
        test
        for path, condition in record_filter.items()
        for test in _tests(ctx.value(entity, path), condition)
    ]
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
    result.body = _rows(ctx, widget.entity, widget.filter, entities)
    if widget.field:
        _read(ctx, widget.entity, [widget.field], entities)
    result.body.append(
        f"return {_aggregate(ctx, widget.entity, widget.aggregate, widget.field, 'rows')};"
    )
    result.format = widget.format
    result.icon = widget.icon
    result.color = css_var(widget.color) if widget.color else None
    if widget.icon:
        plan.icons.add(widget.icon)
    if widget.link:
        result.href = ctx.href(widget.entity, widget.link, {}, "row")
    plan.uses.add("stat")


def _chart(
    ctx: ViewContext,
    plan: DashboardPlan,
    result: WidgetPlan,
    widget: ChartWidget,
    entities: set[str],
) -> None:
    entity = widget.entity
    result.body = _rows(ctx, entity, widget.filter, entities)
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
        key = f"(row) => {group.expr}?.slice(0, 7) ?? null"
        groups = None
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
            item = f"{{ key: {js(enum_value)}, label: {js(text)}"
            if style and style.color:
                item += f", color: {js(css_var(style.color))}"
            items.append(item + " }")
        groups = "[" + ", ".join(items) + "]"
    args = f"rows, {key}, (group) => {total}"
    if groups:
        args += f", {groups}"
    result.body.append(f"return groupRows({args});")
    result.returns = "ChartDatum[]"
    result.chart = widget.chart
    entity_def = ctx.definition.entities[entity]
    result.value_label = (
        entity_def.plural_label or label(entity) + "s"
        if widget.aggregate == "count"
        else ctx.value(entity, widget.field or "").label
    )
    plan.uses.add("chart")


def _list(
    ctx: ViewContext,
    plan: DashboardPlan,
    result: WidgetPlan,
    widget: ListWidget,
    entities: set[str],
) -> None:
    definition = ctx.definition
    assert definition.ui is not None
    view = definition.ui.views[widget.view]
    assert isinstance(view, TableView | CardsView)
    entity = view.entity
    view_plan = ctx.view_plan(widget.view)
    entities.add(entity)
    entities.update(view_plan.lookups)
    result.view = widget.view
    result.body = _rows(ctx, entity, widget.filter, entities)
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
