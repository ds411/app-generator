"""The views of API data in the front-end apps: the answer of an operation (ADR 0022).

A view with `source` shows the answer of an operation of a third-party
API: a table or a card list of its items, or a detail view of an object.
The shared UI templates in `templates/ui/views/` render the values of
this module. The values of a property path are TypeScript expressions
over one item (`item`), with optional chaining after a property that can
be missing or null. The view sorts, searches, and pages the loaded items
in the browser.

The Next.js app calls the operation in the server component of the page,
with the server client of the API, and gives the answer to the view. The
React app calls it in the browser, with the browser client of the API.
"""

import json
import re
from dataclasses import dataclass, field

from appgen.bindings.shared.details import section_grid
from appgen.bindings.shared.integrations import TsApi, TsMethod, ts_apis, ts_key
from appgen.bindings.shared.ui import css_var, js
from appgen.bindings.shared.views import (
    DEFAULT_PAGE_SIZE,
    ViewContext,
    label,
    state_ids,
)
from appgen.dsl.ids import walk_elements
from appgen.dsl.openapi import (
    ArraySchema,
    ClientSpec,
    Property,
    Ref,
    ScalarSchema,
    Schema,
    UnionSchema,
    nullable,
    property_chain,
    resolved,
)
from appgen.dsl.ui.api_data import ApiData, api_data
from appgen.dsl.ui.common import States
from appgen.dsl.ui.states import effective_states
from appgen.dsl.ui.views import (
    ApiCardsView,
    ApiDetailView,
    ApiListViewBase,
    ApiTableView,
    ApiView,
)
from appgen.gen.naming import camel

_IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*$")
_WORD = re.compile(r"[A-Za-z_$][\w$]*")
_ROUTE = re.compile(r"^\$route\.([a-z][a-z0-9_]*)$")
_STRING_FORMATS = {"date": "date", "date-time": "datetime", "email": "email", "uri": "url"}
_TEXT_FORMATS = {"text", "email", "url", "badge", "avatar"}
_ALIGN = {"start": "", "center": "text-center", "end": "text-end"}
_ITEM = "item"


@dataclass(frozen=True, slots=True)
class ApiValue:
    """The value of a property path of an item of API data."""

    path: str
    label: str
    expr: str
    """The raw value, of `item`."""
    text_expr: str
    """The value as text, for the search and the display."""
    format: str
    """The display format, for example `date` or `badge`."""


@dataclass(frozen=True, slots=True)
class ApiColumnPlan:
    """A column of a table of API data."""

    name: str
    element_id: str
    value: ApiValue
    header: str
    cell: str
    """The JSX of a cell, of `item`."""
    sortable: bool
    classes: str
    width: str | None


@dataclass(slots=True)
class ApiCardPlan:
    """The content of the cards of a card list of API data."""

    element_id: str
    title: str
    """The TypeScript text of the title, of `item`."""
    subtitle: str | None = None
    fields: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """The label and the JSX of each field."""
    footer: list[str] = field(default_factory=list[str])


@dataclass(frozen=True, slots=True)
class ApiSectionPlan:
    """A section of a detail view of API data: a card with properties of the answer."""

    element_id: str
    title: str | None
    description: str | None
    fields: list[tuple[str, str]]
    grid: str


@dataclass(frozen=True, slots=True)
class ApiFilterPlan:
    """A search filter of a list of API data."""

    key: str
    """The key of the filter state."""
    element_id: str
    label: str
    match: str
    """The TypeScript test of `item` and `filters`."""


@dataclass(slots=True)
class ApiViewPlan:
    """The values of a view of API data that its template needs."""

    name: str
    view: ApiView
    server: bool
    """True if the server calls the operation and gives the answer to the view (Next.js)."""
    api: TsApi
    method: TsMethod
    item_type: str
    """The TypeScript type of an item of a list, or of the answer of a detail view."""
    items: str
    """The TypeScript list of the items, of `answer`, or `answer` for a detail view."""
    arguments: str | None
    """The TypeScript arguments of the method, of `route`, or None without parameters."""
    empty_answer: bool = False
    """True if the answer of a detail view can be null: the view shows its empty state."""
    route_params: list[str] = field(default_factory=list[str])
    """The path parameters of the page that the arguments read."""
    params_type_used: bool = False
    """True if the arguments name the params type of the method."""
    columns: list[ApiColumnPlan] = field(default_factory=list[ApiColumnPlan])
    card: ApiCardPlan | None = None
    title: str | None = None
    """The TypeScript text of the header title of a detail view, of `item`."""
    subtitle: str | None = None
    """The JSX of the header subtitle of a detail view, of `item`."""
    sections: list[ApiSectionPlan] = field(default_factory=list[ApiSectionPlan])
    filters: list[ApiFilterPlan] = field(default_factory=list[ApiFilterPlan])
    sort: ApiValue | None = None
    sort_desc: bool = False
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
        """The import path of the client of the API."""
        return f"@/shared/api/{self.api.folder}"

    @property
    def call(self) -> str:
        """The TypeScript call of the operation with the client of the API."""
        return f"{self.api.factory}().{self.method.name}({self.arguments or ''})"

    @property
    def answer_type(self) -> str:
        return self.method.returns

    @property
    def props(self) -> bool:
        """Return True if the component of the view has props: the answer or the route.

        The Next.js app gives the answer of the server to the view. The
        React view reads the path parameters of the page that its
        arguments name.
        """
        return self.server or bool(self.route_params)

    def type_names(self) -> list[str]:
        """Return the types of the client that the view names, sorted by name."""
        known = {t.name for t in self.api.types}
        code = " ".join([self.answer_type, self.item_type])
        if not self.server and self.params_type_used and self.method.params_type is not None:
            # In the React app, the view calls the operation.
            known.add(self.method.params_type)
            code += " " + (self.arguments or "")
        return sorted(set(_WORD.findall(code)) & known)

    def code(self) -> str:
        """Return the TypeScript expressions of the view, to find the helpers that they call."""
        parts = [f.match for f in self.filters]
        parts += [c.cell + c.value.expr for c in self.columns]
        parts += [self.sort.expr] if self.sort else []
        card = self.card
        if card is not None:
            parts += [card.title, card.subtitle or "", *(jsx for _, jsx in card.fields)]
            parts += card.footer
        parts += [self.title or "", self.subtitle or ""]
        parts += [jsx for s in self.sections for _, jsx in s.fields]
        return " ".join(parts)

    def element_ids(self) -> list[str]:
        """Return the IDs of the view and of the elements in it, for the traces of a gap."""
        return [element.id for _, element in walk_elements(self.view)]

    def needs(self, name: str) -> bool:
        """Return True if the code of the view calls a helper, for example `formatValue`."""
        return f"{name}(" in self.code()

    def action(self, name: str | None) -> None:
        """A view of API data has no actions: the state macros find none."""
        return None


def build_api_view(context: ViewContext, name: str, server: bool) -> ApiViewPlan:
    """Return the plan of a view of API data; `server` is True for the Next.js app."""
    definition = context.definition
    assert definition.ui is not None
    view = definition.ui.views[name]
    assert isinstance(view, ApiTableView | ApiCardsView | ApiDetailView)
    data = api_data(definition, view)
    assert data is not None and data.item is not None, "The validator checks the source."
    api = ts_apis(definition)[view.api]
    method = next(m for m in api.methods if m.operation_id == view.operation)
    plan = ApiViewPlan(
        name=name,
        view=view,
        server=server,
        api=api,
        method=method,
        item_type=_type_name(data.item, data.spec),
        items=_items(view, data),
        arguments=None,
        empty_answer=isinstance(view, ApiDetailView)
        and data.operation.result is not None
        and nullable(data.operation.result, data.spec),
    )
    _arguments(plan, data)
    plan.states = effective_states(definition, view)
    plan.state_ids = state_ids(definition, view)
    states = plan.states
    # A detail view shows the empty state only for an answer that can be null.
    detail = isinstance(view, ApiDetailView) and not plan.empty_answer
    shown = (states.error,) if detail else (states.empty, states.error)
    plan.icons |= {s.icon for s in shown if s and s.icon}
    if isinstance(view, ApiListViewBase):
        for filter_name, filter_ in view.filters.items():
            texts = [_value(data, path).text_expr for path in filter_.fields]
            match = f"matchesSearch(filters.{camel(filter_name)}, [{', '.join(texts)}])"
            plan.filters.append(
                ApiFilterPlan(
                    camel(filter_name), filter_.id, filter_.label or label(filter_name), match
                )
            )
        if view.sort is not None:
            plan.sort = _value(data, view.sort.field)
            plan.sort_desc = view.sort.direction == "desc"
        pagination = view.pagination
        defaults = definition.ui.defaults
        plan.page_size = (
            (pagination.page_size if pagination else None)
            or (defaults.page_size if defaults else None)
            or DEFAULT_PAGE_SIZE
        )
        plan.page_sizes = sorted(set(pagination.page_sizes if pagination else []))
    if plan.filters:
        plan.uses.add("filters")
    match view:
        case ApiTableView():
            _columns(plan, view, data)
        case ApiCardsView():
            _card(plan, view, data)
        case ApiDetailView():
            _detail(plan, view, data)
    return plan


def _columns(plan: ApiViewPlan, view: ApiTableView, data: ApiData) -> None:
    for name, column in view.columns.items():
        path = column.field or name
        value = _value(data, path, column.format)
        hide = f"max-{column.hide_below}:hidden" if column.hide_below else ""
        plan.columns.append(
            ApiColumnPlan(
                name=name,
                element_id=column.id,
                value=value,
                header=column.label or value.label,
                cell=_jsx(value, plan),
                sortable=column.sortable,
                classes=" ".join(c for c in (_ALIGN[column.align], hide) if c),
                width=css_var(column.width) if column.width else None,
            )
        )


def _card(plan: ApiViewPlan, view: ApiCardsView, data: ApiData) -> None:
    card = view.card
    result = ApiCardPlan(element_id=card.id, title=_value(data, card.title).text_expr)
    if card.subtitle:
        result.subtitle = _jsx(_value(data, card.subtitle), plan)
    for path in card.fields:
        value = _value(data, path)
        result.fields.append((value.label, _jsx(value, plan)))
    for path in card.footer:
        result.footer.append(_jsx(_value(data, path), plan))
    plan.card = result


def _detail(plan: ApiViewPlan, view: ApiDetailView, data: ApiData) -> None:
    header = view.header
    # The view shows the empty state for an answer that is null.
    if header is not None and header.title:
        plan.title = _value(data, header.title, present=True).text_expr
    if header is not None and header.subtitle:
        plan.subtitle = _jsx(_value(data, header.subtitle, present=True), plan)
    for section in view.sections.values():
        fields: list[tuple[str, str]] = []
        for path in section.fields:
            value = _value(data, path, present=True)
            fields.append((value.label, _jsx(value, plan)))
        plan.sections.append(
            ApiSectionPlan(
                element_id=section.id,
                title=section.title,
                description=section.description,
                fields=fields,
                grid=section_grid(section.columns),
            )
        )


def _arguments(plan: ApiViewPlan, data: ApiData) -> None:
    """Set the arguments of the method: the literal values and the path parameters of the page.

    A path parameter is a text: the arguments convert it to the type of
    the parameter. A list parameter gets a list of one value.
    """
    view = plan.view
    parameters = {p.name: p for p in data.operation.parameters}
    parts: list[str] = []
    for name, value in view.params.items():
        parameter = parameters[name]
        schema = resolved(parameter.schema, data.spec)
        listed = False
        if isinstance(schema, ArraySchema):
            listed = True
            schema = resolved(schema.items, data.spec)
        route = _ROUTE.match(value) if isinstance(value, str) else None
        enum = False
        if route is not None:
            param = route.group(1)
            if param not in plan.route_params:
                plan.route_params.append(param)
            code = _from_text(f'route.{param} ?? ""', schema)
            # The text of the path of an enum parameter is one of its values.
            enum = isinstance(schema, ScalarSchema) and bool(schema.enum)
        else:
            code = js(value)
        code = f"[{code}]" if listed else code
        if enum:
            assert plan.method.params_type is not None
            plan.params_type_used = True
            code = f"({code}) as {plan.method.params_type}[{json.dumps(name)}]"
        parts.append(f"{ts_key(name)}: {code}")
    if plan.method.params_type is not None:
        plan.arguments = "{ " + ", ".join(parts) + " }" if parts else "{}"


def _from_text(text: str, schema: Schema) -> str:
    """Return the TypeScript value of a text for a scalar schema."""
    if isinstance(schema, ScalarSchema) and not schema.enum:
        if schema.type in ("integer", "number"):
            return f"Number({text})"
        if schema.type == "boolean":
            return f'({text}) === "true"'
    return text


def _items(view: ApiView, data: ApiData) -> str:
    """Return the TypeScript list of the items, of `answer`, or `answer` for a detail view."""
    if isinstance(view, ApiDetailView):
        return "answer"
    result = data.operation.result
    assert result is not None
    if view.items is None:
        return "(answer ?? [])" if nullable(result, data.spec) else "answer"
    chain = property_chain(result, view.items, data.spec)
    assert chain is not None
    expr, optional = _access("answer", result, chain, data.spec)
    return f"({expr} ?? [])" if optional else expr


def _access(
    base: str, schema: Schema, chain: list[Property], spec: ClientSpec, present: bool = False
) -> tuple[str, bool]:
    """Return the TypeScript access of a property chain, and True if it can be empty.

    With `present`, the base is not null: the code checked it.
    """
    expr = base
    optional = not present and nullable(schema, spec)
    for prop in chain:
        dot = "?." if optional else "."
        if _IDENTIFIER.match(prop.name):
            expr = f"{expr}{dot}{prop.name}"
        else:
            expr = f"{expr}{'?.' if optional else ''}[{json.dumps(prop.name)}]"
        optional = optional or not prop.required or nullable(prop.schema, spec)
    return expr, optional


def _value(data: ApiData, path: str, fmt: str | None = None, present: bool = False) -> ApiValue:
    """Return the value of a property path of an item; `present` if the item is not null."""
    assert data.item is not None
    chain = property_chain(data.item, path, data.spec)
    assert chain is not None, "The validator checks the property paths."
    expr, _ = _access(_ITEM, data.item, chain, data.spec, present)
    schema = resolved(chain[-1].schema, data.spec)
    fmt = fmt or _default_format(schema)
    text = (
        f'String({expr} ?? "")'
        if fmt in _TEXT_FORMATS and _is_text(schema)
        else f'formatValue({expr}, "{fmt if fmt not in ("badge", "avatar") else "text"}")'
    )
    return ApiValue(path, label(chain[-1].name), expr, text, fmt)


def _default_format(schema: Schema) -> str:
    """Return the display format of a property by its schema: an enum is a badge."""
    if not isinstance(schema, ScalarSchema):
        return "text"
    if schema.enum:
        return "badge"
    if schema.type in ("integer", "number"):
        return "number"
    if schema.type == "boolean":
        return "boolean"
    return _STRING_FORMATS.get(schema.format or "", "text")


def _is_text(schema: Schema) -> bool:
    return isinstance(schema, ScalarSchema) and schema.type == "string"


def _jsx(value: ApiValue, plan: ApiViewPlan) -> str:
    """Return the JSX that shows a value of `item`, and note the components it needs."""
    if value.format == "badge":
        plan.uses.add("badge")
        return f"<BadgeValue value={{{value.expr}}} />"
    if value.format == "avatar":
        plan.uses.add("avatar")
        return f"<AvatarValue name={{{value.text_expr}}} />"
    plan.uses.add("formatted")
    return f'<FormattedValue value={{{value.expr}}} format="{value.format}" />'


def _type_name(schema: Schema, spec: ClientSpec) -> str:
    """Return the TypeScript type of an item: the name of its object schema."""
    match schema:
        case Ref(name):
            return name
        case UnionSchema(options):
            others = [o for o in options if not (isinstance(o, ScalarSchema) and o.type == "null")]
            if len(others) == 1:
                return _type_name(others[0], spec)
        case _:
            pass
    raise AssertionError("The item of a view of API data is a named object schema.")
