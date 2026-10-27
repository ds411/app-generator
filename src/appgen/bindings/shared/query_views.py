"""The views of the rows of a query in the front-end apps (ADR 0045).

A view with `query` shows the rows of a query: a table, a card list, or a
calendar. The shared UI template `templates/ui/views/query-view.tsx.j2`
renders the values of this module. The filters of the view give the
params of the query, and the other params come from `params`: a literal
value, or a path parameter of the page. The view loads one page of the
rows with the function of the query (`src/features/<query>`): in the
Next.js app, its server action runs the gap on the server, and in the
React app, it calls the endpoint of the FastAPI app, or the gap with mock
data. The query gives the order of the rows, so the view does not sort
them. A calendar loads all rows, one page of the largest size at a time.

The values of a field are TypeScript expressions over one row (`item`):
a record of the entity of `returns`, or a row of the fields of `result`.
"""

import json
from dataclasses import dataclass, field

from appgen.bindings.shared.ui import css_var, js
from appgen.bindings.shared.views import (
    DEFAULT_PAGE_SIZE,
    Value,
    ViewContext,
    definition_display,
    label,
    state_ids,
)
from appgen.dsl.ids import walk_elements
from appgen.dsl.model import Field, Operation
from appgen.dsl.ui.common import States
from appgen.dsl.ui.states import effective_states
from appgen.dsl.ui.views import (
    QueryCalendarView,
    QueryCardsView,
    QueryFilter,
    QueryTableView,
    QueryView,
)
from appgen.gen.naming import camel, kebab, pascal

_ALIGN = {"start": "", "center": "text-center", "end": "text-end"}
_ROW = "item"
_TEXT_TYPES = frozenset({"string", "text", "email", "url", "uuid"})
_INPUTS = {"integer": "number", "decimal": "number", "date": "date", "datetime": "datetime-local"}
"""The type of the input of a filter of a param, by the type of the param. The default is text."""
CALENDAR_PAGE_SIZE = 200
"""The page size of the loads of a calendar: the largest page of a query."""


@dataclass(frozen=True, slots=True)
class QueryFilterPlan:
    """A filter of a view of a query: the input of the value of one param."""

    key: str
    """The key of the filter state."""
    param: str
    """The key of the param in the params of the query."""
    element_id: str
    label: str
    kind: str
    """`input` (a text, a number, a date, or a date and time), `select` (an enum), or
    `boolean`."""
    initial: str
    """The initial state as TypeScript."""
    state_type: str
    blank: str | None
    """The TypeScript test of `filters` that is true while the filter has no value, or None
    if the filter always has a value (a switch)."""
    value: str
    """The TypeScript value of the param, of `filters`, when the filter has a value."""
    required: bool
    input_type: str = "text"
    """The type of the HTML input of an `input` filter."""
    step: str | None = None
    """The step of a number input: `1` for an integer, `any` for a decimal."""
    options: tuple[tuple[str, str], ...] = ()
    """The value and the label of each option of a select."""

    @property
    def feature(self) -> str:
        """The runtime part of the filter: `param` for an input (see `ViewContext.features`)."""
        return "param" if self.kind == "input" else self.kind


@dataclass(frozen=True, slots=True)
class QueryColumnPlan:
    """A column of a table of the rows of a query."""

    name: str
    element_id: str
    value: Value
    header: str
    cell: str
    """The JSX of a cell, of `item`."""
    classes: str
    width: str | None


@dataclass(slots=True)
class QueryCardPlan:
    """The content of the cards of a card list of the rows of a query."""

    element_id: str
    title: str
    """The TypeScript text of the title, of `item`."""
    subtitle: str | None = None
    fields: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """The label and the JSX of each field."""
    footer: list[str] = field(default_factory=list[str])


@dataclass(frozen=True, slots=True)
class QueryCalendarPlan:
    """The values of a calendar of the rows of a query."""

    start: Value
    end: Value | None
    label: str
    """The TypeScript text of a row, of `item`."""
    date_only: bool
    href: str | None
    """The TypeScript path of the page that a row opens, of `item`, or None."""
    mode: str


@dataclass(slots=True)
class QueryViewPlan:
    """The values of a view of a query that its template needs."""

    name: str
    view: QueryView
    query: str
    operation: Operation
    row_type: str
    """The TypeScript type of a row: the entity of the records, or `<Query>Row`."""
    function: str
    """The function of the query, in `src/features/<query>`."""
    params: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """The key and the TypeScript value of each param that the view gives, of `filters` and
    `route`."""
    route_params: list[str] = field(default_factory=list[str])
    """The path parameters of the page that the params read."""
    filters: list[QueryFilterPlan] = field(default_factory=list[QueryFilterPlan])
    columns: list[QueryColumnPlan] = field(default_factory=list[QueryColumnPlan])
    card: QueryCardPlan | None = None
    calendar: QueryCalendarPlan | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    page_sizes: list[int] = field(default_factory=list[int])
    states: States | None = None
    state_ids: list[str] = field(default_factory=list[str])
    uses: set[str] = field(default_factory=set[str])
    """The value components and helpers that the view uses, for its imports."""
    icons: set[str] = field(default_factory=set[str])
    """The Lucide icons of the states."""

    @property
    def module(self) -> str:
        """The import path of the function of the query."""
        return f"@/features/{kebab(self.query)}"

    @property
    def params_type(self) -> str | None:
        """The TypeScript type of the params of the query, or None if it has no params."""
        return f"{pascal(self.query)}Params" if self.operation.params else None

    @property
    def required(self) -> list[QueryFilterPlan]:
        """The filters of the required params that can have no value."""
        return [f for f in self.filters if f.required and f.blank is not None]

    def entity_types(self) -> dict[str, list[str]]:
        """Return the types that the view imports from each entity slice, by entity name."""
        operation = self.operation
        types: dict[str, list[str]] = {}
        if self.params_type is not None:
            types.setdefault(operation.entity, []).append(self.params_type)
        types.setdefault(operation.row_entity or operation.entity, []).append(self.row_type)
        return {entity: sorted(set(names)) for entity, names in sorted(types.items())}

    def call(self, page: str) -> str:
        """Return the TypeScript call of the function of the query, with `params` and a page."""
        args = ["params", page] if self.params_type is not None else [page]
        return f"{self.function}({', '.join(args)})"

    def code(self) -> str:
        """Return the TypeScript expressions of the view, to find the helpers that they call."""
        parts = [value for _, value in self.params]
        parts += [c.cell + c.value.expr for c in self.columns]
        card = self.card
        if card is not None:
            parts += [card.title, card.subtitle or "", *(jsx for _, jsx in card.fields)]
            parts += card.footer
        calendar = self.calendar
        if calendar is not None:
            parts += [calendar.start.expr, calendar.end.expr if calendar.end else ""]
            parts += [calendar.label, calendar.href or ""]
        return " ".join(parts)

    def element_ids(self) -> list[str]:
        """Return the IDs of the view and of the elements in it."""
        return [element.id for _, element in walk_elements(self.view)]

    def needs(self, name: str) -> bool:
        """Return True if the code of the view calls a helper, for example `formatValue`."""
        return f"{name}(" in self.code()

    def action(self, name: str | None) -> None:
        """A view of a query has no actions: the state macros find none."""
        return None


def build_query_view(context: ViewContext, name: str) -> QueryViewPlan:
    """Return the plan of a view of the rows of a query."""
    definition = context.definition
    assert definition.ui is not None
    view = definition.ui.views[name]
    assert isinstance(view, QueryTableView | QueryCardsView | QueryCalendarView)
    operation = definition.operations[view.query]
    entity = operation.row_entity
    plan = QueryViewPlan(
        name=name,
        view=view,
        query=view.query,
        operation=operation,
        row_type=pascal(entity) if entity else f"{pascal(view.query)}Row",
        function=camel(view.query),
    )
    plan.states = effective_states(definition, view)
    plan.state_ids = state_ids(definition, view)
    # A calendar shows its grid without rows, and no empty state.
    shown = (
        (plan.states.error,)
        if isinstance(view, QueryCalendarView)
        else (plan.states.empty, plan.states.error)
    )
    plan.icons |= {s.icon for s in shown if s and s.icon}
    _params(plan, view)
    if isinstance(view, QueryCalendarView):
        plan.page_size = CALENDAR_PAGE_SIZE
    else:
        pagination = view.pagination
        defaults = definition.ui.defaults
        plan.page_size = (
            (pagination.page_size if pagination else None)
            or (defaults.page_size if defaults else None)
            or DEFAULT_PAGE_SIZE
        )
        plan.page_sizes = sorted(set(pagination.page_sizes if pagination else []))
    match view:
        case QueryTableView():
            _columns(context, plan, view)
        case QueryCardsView():
            _card(context, plan, view)
        case QueryCalendarView():
            _calendar(context, plan, view)
    return plan


def _value(context: ViewContext, plan: QueryViewPlan, name: str, fmt: str | None = None) -> Value:
    """Return the value of a field of a row, of `item`."""
    entity = plan.operation.row_entity
    if entity is not None:
        return context.value(entity, name, fmt, row=_ROW)
    result = plan.operation.result
    assert result is not None, "The validator checks the rows of a query."
    return context.row_value(name, result[name], fmt, row=_ROW)


def _columns(context: ViewContext, plan: QueryViewPlan, view: QueryTableView) -> None:
    entity = plan.operation.row_entity
    for name, column in view.columns.items():
        value = _value(context, plan, column.field or name, column.format)
        cell = context.jsx(value, plan)
        if column.link and entity is not None:
            plan.uses.add("link")
            href = context.href(entity, column.link, {}, _ROW)
            cell = (
                f'<Link href={{{href}}} className="font-medium underline-offset-4 '
                f'hover:underline">{cell}</Link>'
            )
        hide = f"max-{column.hide_below}:hidden" if column.hide_below else ""
        plan.columns.append(
            QueryColumnPlan(
                name=name,
                element_id=column.id,
                value=value,
                header=column.label or value.label,
                cell=cell,
                classes=" ".join(c for c in (_ALIGN[column.align], hide) if c),
                width=css_var(column.width) if column.width else None,
            )
        )


def _card(context: ViewContext, plan: QueryViewPlan, view: QueryCardsView) -> None:
    card = view.card
    result = QueryCardPlan(element_id=card.id, title=_value(context, plan, card.title).text_expr)
    if card.subtitle:
        result.subtitle = context.jsx(_value(context, plan, card.subtitle), plan)
    for name in card.fields:
        value = _value(context, plan, name)
        result.fields.append((value.label, context.jsx(value, plan)))
    for name in card.footer:
        result.footer.append(context.jsx(_value(context, plan, name), plan))
    plan.card = result


def _calendar(context: ViewContext, plan: QueryViewPlan, view: QueryCalendarView) -> None:
    entity = plan.operation.row_entity
    start = _value(context, plan, view.start)
    end = _value(context, plan, view.end) if view.end else None
    label_name = view.label
    if label_name is None:
        assert entity is not None, "The validator checks the label of the rows of a query."
        label_name = definition_display(context.definition.entities[entity])
    href = None
    if view.link and entity is not None:
        plan.uses.add("link")
        href = context.href(entity, view.link, {}, _ROW)
    plan.calendar = QueryCalendarPlan(
        start=start,
        end=end,
        label=_value(context, plan, label_name).text_expr,
        date_only=start.type == "date",
        href=href,
        mode=view.mode,
    )


def _params(plan: QueryViewPlan, view: QueryView) -> None:
    """Set the params that the view gives: the filters, and the values of `params`."""
    params = plan.operation.params
    for filter_name, filter_ in view.filters.items():
        param_name = filter_.param or filter_name
        filter_plan = _filter(plan, filter_name, filter_, param_name, params[param_name])
        plan.filters.append(filter_plan)
        code = filter_plan.value
        if filter_plan.blank is not None and not filter_plan.required:
            code = f"{filter_plan.blank} ? null : {code}"
        plan.params.append((camel(param_name), code))
    for param_name, value in view.params.items():
        param = params[param_name]
        if isinstance(value, str) and value.startswith("$route."):
            route = value.removeprefix("$route.")
            if route not in plan.route_params:
                plan.route_params.append(route)
            code = _from_text(plan, param_name, param, f'route.{route} ?? ""')
        else:
            code = js(value)
        plan.params.append((camel(param_name), code))


def _filter(
    plan: QueryViewPlan, name: str, filter_: QueryFilter, param_name: str, param: Field
) -> QueryFilterPlan:
    key = camel(name)
    state = f"filters.{key}"
    text = filter_.label or param.label or label(param_name)
    default = filter_.default
    if param.type == "boolean":
        # A switch: on gives true. Off gives false to a required param, else no value.
        return QueryFilterPlan(
            key=key,
            param=camel(param_name),
            element_id=filter_.id,
            label=text,
            kind="boolean",
            initial=js(bool(default)),
            state_type="boolean",
            blank=None,
            value=state if param.required else f"{state} ? true : null",
            required=param.required,
        )
    if param.type == "enum":
        return QueryFilterPlan(
            key=key,
            param=camel(param_name),
            element_id=filter_.id,
            label=text,
            kind="select",
            initial=js(default),
            state_type="string | null",
            blank=f"{state} === null",
            value=f"{state} as {plan.params_type}[{json.dumps(camel(param_name))}]",
            required=param.required,
            options=tuple((v, label(v)) for v in param.values or ()),
        )
    input_type = _INPUTS.get(param.type, "text")
    initial = "" if default is None else str(default)
    if param.type == "datetime":
        # The input shows the local date and time, without the seconds and the time zone.
        initial = initial[:16]
    trimmed = f"{state}.trim()"
    return QueryFilterPlan(
        key=key,
        param=camel(param_name),
        element_id=filter_.id,
        label=text,
        kind="input",
        initial=js(initial),
        state_type="string",
        blank=f'{trimmed} === ""',
        value=_from_text(plan, param_name, param, trimmed, local=True),
        required=param.required,
        input_type=input_type,
        step={"integer": "1", "decimal": "any"}.get(param.type),
    )


def _from_text(plan: QueryViewPlan, name: str, param: Field, text: str, local: bool = False) -> str:
    """Return the TypeScript value of a param from a text.

    `local` is True for the text of a `datetime-local` input: the value is
    the instant in ISO 8601, in UTC.
    """
    match param.type:
        case "integer" | "decimal":
            return f"Number({text})"
        case "boolean":
            return f'({text}) === "true"'
        case "datetime" if local:
            return f"new Date({text}).toISOString()"
        case "enum":
            return f"({text}) as {plan.params_type}[{json.dumps(camel(name))}]"
        case _:
            assert param.type in _TEXT_TYPES | {"date", "datetime"}, param.type
            return text
