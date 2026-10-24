"""The list views of the front-end apps: tables, card lists, and boards (ADR 0003).

The shared UI templates in `templates/ui/views/` render the values of this
module. A view reads all records of its entity and of the entities that
its field paths go through, and filters, sorts, and pages the records in
the browser. The values of a field path are TypeScript expressions over a
record (`row`) and the related records (`lookups`), for example
`lookups.person.get(row.ownerId ?? "")?.name`.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol

from appgen.bindings.shared.gaps import gap_spec
from appgen.bindings.shared.ui import css_class_var, css_var, js
from appgen.dsl.model import AppDefinition, Entity, Field, Relation
from appgen.dsl.ui.common import (
    Action,
    FormAction,
    Grid,
    NavigateAction,
    OperationAction,
    States,
)
from appgen.dsl.ui.fields import resolve_path
from appgen.dsl.ui.states import effective_states
from appgen.dsl.ui.views import (
    BadgeSet,
    BoardView,
    BooleanFilter,
    CardsView,
    DateRangeFilter,
    Filter,
    SearchFilter,
    SelectFilter,
    TableView,
    View,
)
from appgen.gen.binding import Output
from appgen.gen.naming import camel, pascal, words
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.shared.dashboards import DashboardPlan
    from appgen.bindings.shared.details import DetailPlan

type ValueKind = Literal["field", "id", "one", "many"]

_DEFAULT_FORMATS = {
    "string": "text",
    "text": "text",
    "email": "email",
    "url": "url",
    "uuid": "text",
    "integer": "number",
    "decimal": "number",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "enum": "text",
    "json": "text",
}
DEFAULT_PAGE_SIZE = 20
_BOARD_AREA_CLASSES = "w-full min-w-0"
_BOARD_CLASSES = "flex w-max gap-4 px-1 pb-4"
_COLUMN_CLASSES = (
    "flex w-72 shrink-0 flex-col gap-2 rounded-xl border bg-muted/40 p-2 transition-colors"
)
_VIEWPORT = "[&>[data-slot=scroll-area-viewport]]:"
_SCROLLBAR = "[&>[data-slot=scroll-area-scrollbar]]:"
_RESPONSIVE_BOARD = {
    "stack": (f"{_SCROLLBAR}hidden", "w-full flex-col", "w-full"),
    "scroll": (f"{_VIEWPORT}snap-x {_VIEWPORT}snap-mandatory", "", "w-[85vw] snap-start"),
}
"""The classes of the scroll area, of the row, and of a column of a board below the
breakpoint of its hint. The scroll area scrolls the row: a stacked board hides its
scroll bar, and a board with snap sets the snap on the viewport of the area."""


def label(name: str) -> str:
    """Return a display label for a name: `due_date` gives `Due date`."""
    text = " ".join(words(name))
    return text[:1].upper() + text[1:]


@dataclass(frozen=True, slots=True)
class Value:
    """The value of a field path for one record of a view."""

    path: str
    label: str
    kind: ValueKind
    type: str
    """The field type, `relation`, or `uuid` for `id`."""
    expr: str
    """The raw value: a field value, the related record, or the list of related records."""
    key_expr: str
    """The value that a filter compares: the ID for a relation, else the raw value."""
    text_expr: str
    """The value as text, for the search, the sort of relations, and the display."""
    sort_expr: str
    """The value that the sort compares."""
    format: str
    """The display format, for example `date`, `badge`, or `avatar`."""
    badge: str | None = None
    """The camel-case name of the badge set, or None."""
    enum_values: tuple[str, ...] = ()
    target: str | None = None
    """The target entity of a relation."""
    currency: str | None = None
    """The ISO 4217 code of a `currency` value, or None for the default currency."""


@dataclass(frozen=True, slots=True)
class FilterPlan:
    """A filter of a list view, with its state key and its match expression."""

    name: str
    key: str
    element_id: str
    kind: str
    label: str
    default: str
    """The initial state as TypeScript."""
    state_type: str
    match: str
    """A TypeScript condition that is true for a row that the filter keeps."""
    value: Value | None = None
    multiple: bool = False
    options: str | None = None
    """A TypeScript expression of the options `{ value, label }[]` of a select."""


@dataclass(frozen=True, slots=True)
class ActionPlan:
    """An action that the template can render, with the TypeScript that runs it."""

    name: str
    element_id: str
    action: Action
    label: str
    href: str | None = None
    """For a navigate action: a TypeScript expression of the path, of `record`."""
    run: str | None = None
    """For an operation or a custom action: a TypeScript expression of `records`."""
    navigate_to: str | None = None
    """The TypeScript path of the page that opens after a success, or None."""
    form: str | None = None
    """For a form action that opens a dialog or a sheet: the name of the form."""
    imports: tuple[str, ...] = ()
    only_pages: tuple[str, ...] = ()
    """For a top bar action: the pages that show it. Empty: all pages, except `except_pages`."""
    except_pages: tuple[str, ...] = ()
    """For a top bar action: the pages that do not show it (`placement: page`)."""


@dataclass(frozen=True, slots=True)
class FormRef:
    """A form that a view opens: its component, its module, and what it needs."""

    name: str
    component: str
    module: str
    record: bool
    """True if the form needs the record of the action."""
    route_params: bool
    """True if the form reads the path parameters of the page."""


@dataclass(frozen=True, slots=True)
class ColumnPlan:
    """A column of a table view."""

    name: str
    element_id: str
    value: Value
    header: str
    cell: str
    """The JSX of a cell, of `row`."""
    sortable: bool
    classes: str
    width: str | None


@dataclass(slots=True)
class CardPlan:
    """The content of the cards of a card list or a board."""

    element_id: str | None
    title: str
    """The JSX of the title, of `row`."""
    href: str | None
    """The path that the title opens, of `row`, or None."""
    subtitle: str | None = None
    badge: str | None = None
    badge_id: str | None = None
    fields: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """The label and the JSX of each field."""
    footer: list[str] = field(default_factory=list[str])


@dataclass(frozen=True, slots=True)
class BoardColumnPlan:
    """A column of a board: one value of the group field."""

    value: str
    label: str
    color: str | None
    limit: int | None
    element_id: str | None


@dataclass(slots=True)
class ViewPlan:
    """The values of a list view that its template needs."""

    name: str
    view: View
    entity: str
    lookups: list[str] = field(default_factory=list[str])
    """The related entities that the view reads, sorted by name."""
    filters: list[FilterPlan] = field(default_factory=list[FilterPlan])
    sort: Value | None = None
    sort_desc: bool = False
    page_size: int = DEFAULT_PAGE_SIZE
    page_sizes: list[int] = field(default_factory=list[int])
    states: States | None = None
    state_ids: list[str] = field(default_factory=list[str])
    """The element IDs of the states that the view shows, for the traces."""
    actions: list[ActionPlan] = field(default_factory=list[ActionPlan])
    hidden_actions: list[str] = field(default_factory=list[str])
    """The IDs of the view actions that the top bar also has: the view hides them."""
    row_actions: list[ActionPlan] = field(default_factory=list[ActionPlan])
    bulk_actions: list[ActionPlan] = field(default_factory=list[ActionPlan])
    imports: list[str] = field(default_factory=list[str])
    """The import lines of the actions."""
    columns: list[ColumnPlan] = field(default_factory=list[ColumnPlan])
    initial_sort: str | None = None
    """The column that the table sorts by first, or None."""
    card: CardPlan | None = None
    group_by: Value | None = None
    board_columns: list[BoardColumnPlan] = field(default_factory=list[BoardColumnPlan])
    board_area_classes: str = _BOARD_AREA_CLASSES
    """The Tailwind CSS classes of the scroll area of a board."""
    board_classes: str = _BOARD_CLASSES
    """The Tailwind CSS classes of the row of board columns."""
    column_classes: str = _COLUMN_CLASSES
    """The Tailwind CSS classes of a board column."""
    move: str | None = None
    """The TypeScript that moves `record` to the column `value` of a board."""
    forms: list[FormRef] = field(default_factory=lambda: list[FormRef]())
    """The forms that the actions of the view open in a dialog or a sheet."""
    uses: set[str] = field(default_factory=set[str])
    """The value components and helpers that the view uses, for its imports."""
    icons: set[str] = field(default_factory=set[str])
    """The Lucide icons that the view uses."""

    @property
    def type(self) -> str:
        return pascal(self.entity)

    @property
    def var(self) -> str:
        return camel(self.entity)

    def code(self) -> str:
        """Return the TypeScript expressions of the view, to find the helpers that they call."""
        parts = [f.match + (f.options or "") for f in self.filters]
        parts += [c.cell + c.value.sort_expr for c in self.columns]
        parts += [self.sort.sort_expr] if self.sort else []
        card = self.card
        if card is not None:
            parts += [card.title, card.href or "", card.subtitle or "", card.badge or ""]
            parts += [jsx for _, jsx in card.fields] + card.footer
        actions = [*self.actions, *self.row_actions, *self.bulk_actions]
        parts += [(a.href or "") + (a.run or "") + (a.navigate_to or "") for a in actions]
        parts += [self.move or ""]
        return " ".join(parts)

    def needs(self, name: str) -> bool:
        """Return True if the code of the view calls a helper, for example `formatValue`."""
        return f"{name}(" in self.code()

    def row_action(self, name: str | None) -> ActionPlan | None:
        """Return a row action by name, if the template can render it."""
        return next((a for a in self.row_actions if a.name == name), None)

    def action(self, name: str | None) -> ActionPlan | None:
        """Return a view action by name, if the template can render it."""
        return next((a for a in self.actions if a.name == name), None)


@dataclass(slots=True)
class ActionBarPlan:
    """The actions of a page header or of a top bar, outside of a view.

    The actions of a page with a record (a page with an entity and path
    parameters) get the record of the last path parameter. The actions of
    a top bar have no record.
    """

    element_id: str
    """The ID of the page or of the top bar."""
    component: str
    """The name of the React component."""
    type: str
    """The TypeScript type of the records of the actions."""
    entity: str | None = None
    """The entity of the record, for a page with a record."""
    param: str | None = None
    """The path parameter with the ID of the record."""
    actions: list[ActionPlan] = field(default_factory=list[ActionPlan])
    hidden_actions: list[str] = field(default_factory=list[str])
    """The IDs of the page actions that the page header does not show, and that the
    top bar does not render for the page: the top bar has the same action."""
    record_actions: set[str] = field(default_factory=set[str])
    """The actions that need the record."""
    forms: list[FormRef] = field(default_factory=list[FormRef])
    imports: list[str] = field(default_factory=list[str])
    icons: set[str] = field(default_factory=set[str])

    @property
    def var(self) -> str:
        return camel(self.entity or "")

    def code(self) -> str:
        """Return the TypeScript expressions of the actions, to find the helpers that they call."""
        return " ".join(
            (a.href or "") + (a.run or "") + (a.navigate_to or "") for a in self.actions
        )

    def needs(self, name: str) -> bool:
        """Return True if the code of the actions calls a helper, for example `pageHref`."""
        return f"{name}(" in self.code()

    @property
    def per_page(self) -> bool:
        """Return True if an action of the top bar shows only on some pages."""
        return any(a.only_pages or a.except_pages for a in self.actions)


class UsesParts(Protocol):
    """A plan that notes the value components that its JSX uses."""

    uses: set[str]


class ViewContext:
    """The values that the view templates read: badges, values, and view plans."""

    def __init__(self, definition: AppDefinition, *, forms: bool = False) -> None:
        """Make the context; `forms` is True if the binding generates the forms (`form_rules`)."""
        self.definition = definition
        self.with_forms = forms
        ui = definition.ui
        self.badge_sets: dict[str, BadgeSet] = dict(ui.badges) if ui else {}
        self.list_views: dict[str, str] = {
            name: view.kind
            for name, view in (ui.views.items() if ui else ())
            if isinstance(view, TableView | CardsView | BoardView)
        }
        """The kind of each list view (`table`, `cards`, or `board`), by name."""
        self.detail_views: list[str] = [
            name for name, view in (ui.views.items() if ui else ()) if view.kind == "detail"
        ]
        self.dashboards: list[str] = list(ui.dashboards) if ui else []
        self._plans: dict[str, ViewPlan] = {}
        # A local import: the forms module imports this module.
        from appgen.bindings.shared.forms import FormContext

        self.forms = FormContext(definition)
        self._details: dict[str, Any] = {}
        self._dashboards: dict[str, Any] = {}
        self._bars: dict[str, ActionBarPlan] = {}

    @property
    def runtime(self) -> bool:
        """Return True if the app has views, dashboards, or page actions: they need the runtime."""
        return bool(
            self.list_views or self.detail_views or self.dashboards or self.page_action_bars
        )

    @property
    def page_action_bars(self) -> list[str]:
        """Return the pages with actions in the page header that the templates can render."""
        return [
            name for name, page in self.definition.pages.items() if self.action_bar(page.id).actions
        ]

    def action_bar(self, element_id: str) -> ActionBarPlan:
        """Return the plan of the actions of a page (`pages.<name>`) or a top bar."""
        if element_id not in self._bars:
            self._bars[element_id] = self._build_bar(element_id)
        return self._bars[element_id]

    def _build_bar(self, element_id: str) -> ActionBarPlan:
        definition = self.definition
        parts = element_id.split(".")
        if parts[0] == "pages":
            page = definition.pages[parts[1]]
            params = _path_params(page.path)
            entity = page.entity if params else None
            plan = ActionBarPlan(
                element_id=element_id,
                component=f"{pascal(parts[1])}PageActions",
                type=pascal(entity) if entity else "never",
                entity=entity,
                param=params[-1] if entity else None,
            )
            items = list(page.actions.items())
            unplaced = [(n, a) for n, a in items if a.placement is None]
            hidden = self._topbar_duplicates([parts[1]], unplaced)
            # The top bar renders an action with `placement: topbar` or `both`, unless
            # the top bar already has the same action.
            in_bar = set(self._topbar_duplicates([parts[1]], items))
            hidden += [n for n, a in items if a.placement == "topbar" and n in in_bar]
            plan.hidden_actions = [page.actions[n].id for n, _ in items if n in hidden]
            items = [(n, a) for n, a in items if n not in hidden and a.placement != "topbar"]
            extra: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        else:
            # `ui.layouts.<layout>.topbar`
            assert definition.ui is not None
            topbar = definition.ui.layouts[parts[2]].topbar
            assert topbar is not None
            plan = ActionBarPlan(
                element_id=element_id,
                component=f"{pascal(parts[2])}TopbarActions",
                type="never",
            )
            items, extra = self._topbar_items(parts[2], list(topbar.actions.items()))
        for name, action in items:
            entity = plan.entity or self._action_entity(action)
            if entity is None:
                continue
            row = self._action(entity, name, action, "row" if plan.entity else "view")
            if row is not None and name in extra:
                row = replace(row, only_pages=extra[name][0], except_pages=extra[name][1])
            if row is None or "lookups." in (row.href or ""):
                if name in extra and extra[name][0]:
                    raise GenerationError(
                        f"The action '{action.id}' needs the record of its page, so the top "
                        "bar cannot show it. Use 'placement: page'."
                    )
                continue
            plan.actions.append(row)
            code = (row.href or "") + (row.run or "")
            if "record" in code:
                plan.record_actions.add(name)
        plan.forms = self.form_refs(plan.actions)
        record_forms = {f.name for f in plan.forms if f.record}
        plan.record_actions |= {a.name for a in plan.actions if a.form in record_forms}
        if not plan.record_actions:
            # No action needs the record, so the page does not read it.
            plan.entity, plan.param, plan.type = None, None, "never"
        plan.imports = sorted({line for a in plan.actions for line in a.imports})
        plan.icons = {a.action.icon for a in plan.actions if a.action.icon}
        return plan

    def _topbar_items(
        self, layout: str, own: list[tuple[str, Action]]
    ) -> tuple[list[tuple[str, Action]], dict[str, tuple[tuple[str, ...], tuple[str, ...]]]]:
        """Return the actions of a top bar, with the pages that show each one.

        The top bar shows its own actions on each page, except on a page
        with the same action and `placement: page`. A page action with
        `placement: topbar` or `both` that the top bar does not have shows
        in the top bar on its page only. Its name gets the page name as a
        prefix, so that two pages can have actions with the same name.
        """
        from appgen.bindings.shared.ui import ui_plan

        items = list(own)
        extra: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        keys = {name: _action_key(action) for name, action in own}
        excluded: dict[str, list[str]] = {name: [] for name, _ in own}
        for info in ui_plan(self.definition).pages_of(layout):
            for name, action in info.page.actions.items():
                key = _action_key(action)
                same = [n for n, k in keys.items() if k is not None and k == key]
                if action.placement == "page":
                    for n in same:
                        excluded[n].append(info.name)
                elif action.placement in ("topbar", "both") and not same:
                    bar_name = f"{info.name}_{name}"
                    items.append((bar_name, action))
                    extra[bar_name] = ((info.name,), ())
        for name, pages in excluded.items():
            if pages:
                extra[name] = ((), tuple(pages))
        return items, extra

    def _topbar_duplicates(
        self, pages: list[str], actions: Iterable[tuple[str, Action]]
    ) -> list[str]:
        """Return the names of the actions that the top bar of each page also has, in order.

        An action is the same if it has the same kind and the same target
        (the form, the operation, or the page). The top bar shows it, so a
        page or a view does not show it a second time. A view on no page
        hides no action.
        """
        if not pages or self.definition.ui is None:
            return []
        from appgen.bindings.shared.ui import ui_plan

        plan = ui_plan(self.definition)
        layouts = self.definition.ui.layouts
        shared: set[tuple[str, str]] | None = None
        for page_name in pages:
            layout = plan.pages[page_name].layout
            topbar = layouts[layout].topbar if layout in layouts else None
            actions_of_bar = topbar.actions.values() if topbar else ()
            keys = {key for a in actions_of_bar if (key := _action_key(a)) is not None}
            shared = keys if shared is None else shared & keys
        return [name for name, action in actions if _action_key(action) in (shared or set())]

    def _action_entity(self, action: Action) -> str | None:
        """Return an entity for an action without a record: the entity of its form or page."""
        definition = self.definition
        if isinstance(action, FormAction):
            return definition.ui.forms[action.form].entity if definition.ui else None
        if isinstance(action, NavigateAction):
            return definition.pages[action.page].entity or next(iter(definition.entities))
        return next(iter(definition.entities))

    def detail_plan(self, name: str) -> DetailPlan:
        """Return the plan of a detail view (see `appgen.bindings.shared.details`)."""
        from appgen.bindings.shared.details import build_detail

        if name not in self._details:
            self._details[name] = build_detail(self, name)
        return self._details[name]

    def dashboard_plan(self, name: str) -> DashboardPlan:
        """Return the plan of a dashboard (see `appgen.bindings.shared.dashboards`)."""
        from appgen.bindings.shared.dashboards import build_dashboard

        if name not in self._dashboards:
            self._dashboards[name] = build_dashboard(self, name)
        return self._dashboards[name]

    @property
    def badge_icons(self) -> list[str]:
        """Return the Lucide icons of the badge sets, sorted by name."""
        return sorted(
            {v.icon for s in self.badge_sets.values() for v in s.values.values() if v.icon}
        )

    @property
    def features(self) -> set[str]:
        """Return the runtime parts that the list views need, for the outputs and shadcn/ui.

        The parts are the view kinds, the filter kinds (`search`, `boolean`,
        `date_range`, `select`, `multi_select`), and the value components
        (`badge`, `avatar`, `formatted`).
        """
        found: set[str] = set()
        values = {"badge", "avatar", "formatted"}
        for name, kind in self.list_views.items():
            plan = self.view_plan(name)
            found.add(kind)
            found |= plan.uses & values
            for f in plan.filters:
                found.add("multi_select" if f.multiple else f.kind)
        for name in self.detail_views:
            found.add("detail")
            found |= self.detail_plan(name).uses & values
        for name in self.dashboards:
            dashboard = self.dashboard_plan(name)
            found.add("dashboard")
            found |= dashboard.uses & {"chart"}
            for widget in dashboard.widgets:
                found |= {c for col in widget.columns for c in _value_parts(col.cell)}
                card = widget.card
                if card is not None:
                    code = " ".join([card.title, card.subtitle or "", card.badge or ""])
                    found |= _value_parts(code)
        return found

    def badge_for(self, entity: str, path: str) -> str | None:
        """Return the badge set of an enum field, by the `field` key of the sets."""
        target = resolve_path(self.definition, entity, path)
        for name, badge_set in self.badge_sets.items():
            if badge_set.field == f"{target.entity}.{target.name}":
                return name
        return None

    def value(
        self,
        entity: str,
        path: str,
        fmt: str | None = None,
        badge: str | None = None,
        row: str = "row",
    ) -> Value:
        """Return the value of a field path of an entity."""
        definition = self.definition
        expr = row
        current = entity
        optional = False
        segments = path.split(".")
        for segment in segments[:-1]:
            relation = definition.entities[current].relations[segment]
            key = f"{expr}{'?.' if optional else '.'}{camel(segment)}Id"
            expr = f'lookups.{camel(relation.target)}.get({key} ?? "")'
            current = relation.target
            optional = True
        last = segments[-1]
        dot = "?." if optional else "."
        target = resolve_path(definition, entity, path)
        member = target.member
        member_label = label(last)
        if isinstance(member, Field):
            member_label = member.label or member_label
            raw = f"{expr}{dot}{camel(last)}"
            if fmt is None and badge is None:
                fmt = member.format
            if fmt is None or fmt == "badge":
                badge = badge or (self.badge_for(entity, path) if member.type == "enum" else None)
            enum_values = tuple(member.values or ()) if member.type == "enum" else ()
            fmt = fmt or ("badge" if badge else _DEFAULT_FORMATS[member.type])
            currency = member.currency if fmt == "currency" else None
            currency_arg = f", {js(currency)}" if currency else ""
            text = (
                f'String({raw} ?? "")'
                if member.type in ("string", "text", "email", "url", "enum")
                else f'formatValue({raw}, "{fmt if fmt not in ("badge", "avatar") else "text"}"'
                f"{currency_arg})"
            )
            return Value(
                path=path,
                label=member_label,
                kind="field",
                type=member.type,
                expr=raw,
                key_expr=raw,
                text_expr=text,
                sort_expr=raw,
                format=fmt,
                badge=camel(badge) if badge else None,
                enum_values=enum_values,
                currency=currency,
            )
        if member is None:
            raw = f"{expr}{dot}id"
            return Value(path, "ID", "id", "uuid", raw, raw, raw, raw, fmt or "text")
        assert isinstance(member, Relation)
        member_label = member.label or member_label
        target_entity = member.target
        display = self.display_field(target_entity)
        lookup = f"lookups.{camel(target_entity)}"
        if member.kind in ("many_to_one", "one_to_one"):
            key = f"{expr}{dot}{camel(last)}Id"
            record = f'{lookup}.get({key} ?? "")'
            text = f'String({record}?.{display} ?? "")'
            return Value(
                path=path,
                label=member_label,
                kind="one",
                type="relation",
                expr=record,
                key_expr=f"{key} ?? null",
                text_expr=text,
                sort_expr=text,
                format=fmt or "text",
                target=target_entity,
            )
        ids = f"({expr}{dot}{camel(last)} ?? [])"
        records = f"{ids}.flatMap((id) => {lookup}.get(id) ?? [])"
        text = f'{records}.map((item) => String(item.{display} ?? "")).join(", ")'
        return Value(
            path=path,
            label=member_label,
            kind="many",
            type="relation",
            expr=records,
            key_expr=ids,
            text_expr=text,
            sort_expr=text,
            format=fmt or "text",
            target=target_entity,
        )

    def display_field(self, entity: str) -> str:
        """Return the TypeScript key of the display field of an entity."""
        return camel(definition_display(self.definition.entities[entity]))

    def view_plan(self, name: str) -> ViewPlan:
        """Return the plan of a list view."""
        if name not in self._plans:
            self._plans[name] = self._build(name)
        return self._plans[name]

    def _build(self, name: str) -> ViewPlan:
        definition = self.definition
        assert definition.ui is not None
        view = definition.ui.views[name]
        plan = ViewPlan(name=name, view=view, entity=view.entity)
        paths: list[str] = []
        if isinstance(view, TableView):
            paths += [column.field or column_name for column_name, column in view.columns.items()]
        if isinstance(view, CardsView | BoardView):
            paths += self.card_paths(view)
        if isinstance(view, TableView | CardsView):
            for filter_name, filter_ in view.filters.items():
                plan.filters.append(self._filter(view.entity, filter_name, filter_))
                paths += filter_.fields if isinstance(filter_, SearchFilter) else [filter_.field]
            pagination = view.pagination
            defaults = definition.ui.defaults
            plan.page_size = (
                (pagination.page_size if pagination else None)
                or (defaults.page_size if defaults else None)
                or DEFAULT_PAGE_SIZE
            )
            plan.page_sizes = sorted(set(pagination.page_sizes if pagination else []))
        if isinstance(view, TableView | CardsView | BoardView) and view.sort is not None:
            plan.sort = self.value(view.entity, view.sort.field)
            plan.sort_desc = view.sort.direction == "desc"
            paths.append(view.sort.field)
        plan.lookups = sorted(self._lookups(view.entity, paths))
        plan.states = effective_states(definition, view)
        plan.state_ids = state_ids(definition, view)
        pages = [
            page_name
            for page_name, page in definition.pages.items()
            if page.content is not None and page.content.view == name
        ]
        hidden = self._topbar_duplicates(pages, view.actions.items())
        plan.hidden_actions = [view.actions[n].id for n in hidden]
        plan.actions = self._actions(
            view.entity, [(n, a) for n, a in view.actions.items() if n not in hidden], "view"
        )
        if isinstance(view, TableView | CardsView | BoardView):
            plan.row_actions = self._actions(view.entity, view.row_actions.items(), "row")
        if isinstance(view, TableView):
            plan.bulk_actions = self._actions(view.entity, view.bulk_actions.items(), "bulk")
        all_actions = [*plan.actions, *plan.row_actions, *plan.bulk_actions]
        plan.imports = sorted({line for action in all_actions for line in action.imports})
        plan.forms = self.form_refs(all_actions)
        plan.icons |= {a.action.icon for a in all_actions if a.action.icon}
        states = plan.states
        plan.icons |= {s.icon for s in (states.empty, states.error) if s and s.icon}
        if isinstance(view, TableView):
            self._columns(plan, view)
        if isinstance(view, CardsView | BoardView):
            plan.card = self._card(plan, view)
        if isinstance(view, BoardView):
            self._board(plan, view)
        if plan.filters:
            plan.uses.add("filters")
        return plan

    def jsx(self, value: Value, plan: UsesParts, avatar: bool = False) -> str:
        """Return the JSX that shows a value of `row`, and note the components it needs."""
        if value.format == "badge":
            plan.uses.add("badge")
            badge = f"badges.{value.badge}" if value.badge else "undefined"
            return f"<BadgeValue set={{{badge}}} value={{{value.expr}}} />"
        if value.format == "avatar" or (avatar and value.kind == "one"):
            plan.uses.add("avatar")
            return f"<AvatarValue name={{{value.text_expr}}} />"
        plan.uses.add("formatted")
        if value.kind in ("one", "many"):
            return f"<FormattedValue value={{{value.text_expr}}} />"
        fmt = value.format if value.format != "avatar" else "text"
        currency = f" currency={js(value.currency)}" if value.currency else ""
        return f'<FormattedValue value={{{value.expr}}} format="{fmt}"{currency} />'

    def href(self, entity: str, page_name: str, params: dict[str, str], row: str) -> str:
        """Return the TypeScript path of a page for a record, with the page parameters.

        A parameter takes the field path that `params` gives, else the field
        with its name, and the last parameter takes the ID of the record.
        """
        page = self.definition.pages[page_name]
        names = _path_params(page.path)
        entity_members = self.definition.entities[entity]
        parts: list[str] = []
        for index, name in enumerate(names):
            path = params.get(name)
            if path is None:
                last = index == len(names) - 1
                known = name in entity_members.fields or name in entity_members.relations
                path = name if known and not last else "id"
            key = self.value(entity, path, row=row).key_expr
            parts.append(f"{name}: String({key})")
        args = js(camel(page_name))
        if parts:
            args += f", {{ {', '.join(parts)} }}"
        return f"pageHref({args})"

    def _columns(self, plan: ViewPlan, view: TableView) -> None:
        sort_path = view.sort.field if view.sort else None
        for name, column in view.columns.items():
            path = column.field or name
            value = self.value(view.entity, path, column.format, column.badge)
            cell = self.jsx(value, plan)
            if column.link:
                plan.uses.add("link")
                href = self.href(view.entity, column.link, {}, "row")
                cell = (
                    f'<Link href={{{href}}} className="font-medium underline-offset-4 '
                    f'hover:underline" onClick={{(event) => event.stopPropagation()}}>{cell}</Link>'
                )
            align = {"start": "", "center": "text-center", "end": "text-right"}[column.align]
            hide = f"max-{column.hide_below}:hidden" if column.hide_below else ""
            plan.columns.append(
                ColumnPlan(
                    name=name,
                    element_id=column.id,
                    value=value,
                    header=column.label or value.label,
                    cell=cell,
                    sortable=column.sortable,
                    classes=" ".join(c for c in (align, hide) if c),
                    width=css_var(column.width) if column.width else None,
                )
            )
            if sort_path == path and plan.initial_sort is None:
                plan.initial_sort = name

    def _card(self, plan: ViewPlan, view: CardsView | BoardView) -> CardPlan:
        card = view.card
        entity = self.definition.entities[view.entity]
        title_value = self.value(
            view.entity, card.title if card and card.title else definition_display(entity)
        )
        navigate = next(
            (a for a in view.row_actions.values() if isinstance(a, NavigateAction)), None
        )
        href = self.href(view.entity, navigate.page, navigate.params, "row") if navigate else None
        if href:
            plan.uses.add("link")
        title = (
            title_value.text_expr
            if title_value.kind != "field"
            else f'String({title_value.expr} ?? "")'
        )
        result = CardPlan(element_id=card.id if card else None, title=f"{{{title}}}", href=href)
        if card is None:
            return result
        if card.subtitle:
            result.subtitle = self.jsx(self.value(view.entity, card.subtitle), plan)
        if card.badge:
            value = self.value(view.entity, card.badge.field, "badge", card.badge.badge)
            result.badge = self.jsx(value, plan)
            result.badge_id = card.badge.id
        for path in card.fields:
            value = self.value(view.entity, path)
            result.fields.append((value.label, self.jsx(value, plan)))
        for path in card.footer:
            result.footer.append(self.jsx(self.value(view.entity, path), plan, avatar=True))
        return result

    def _board(self, plan: ViewPlan, view: BoardView) -> None:
        group = self.value(view.entity, view.group_by)
        plan.group_by = group
        badge = self.badge_sets.get(_badge_name(group.badge, self.badge_sets) or "")
        for value in group.enum_values:
            column = view.columns.get(value)
            style = badge.values.get(value) if badge else None
            color_ref = (column.color if column else None) or (style.color if style else None)
            plan.board_columns.append(
                BoardColumnPlan(
                    value=value,
                    label=(column.label if column else None)
                    or (style.label if style else None)
                    or label(value),
                    color=css_var(color_ref) if color_ref else None,
                    limit=column.limit if column else None,
                    element_id=column.id if column else None,
                )
            )
        if view.responsive is not None:
            below = f"max-{view.responsive.below}:"
            area, row, column_extra = _RESPONSIVE_BOARD[view.responsive.layout]
            plan.board_area_classes += "".join(f" {below}{c}" for c in area.split())
            plan.board_classes += "".join(f" {below}{c}" for c in row.split())
            plan.column_classes += "".join(f" {below}{c}" for c in column_extra.split())
        key = f"{camel(view.group_by)}: value as {plan.type}[{js(camel(view.group_by))}]"
        operation = self.definition.operations.get(view.move or "")
        if operation is not None and operation.kind == "update":
            op = camel(view.move or "")
            plan.move = f"{op}(record.id, {{ {key} }})"
            plan.imports = sorted(
                {*plan.imports, f'import {{ {op} }} from "@/entities/{_kebab(view.entity)}";'}
            )
        else:
            plan.move = f"{plan.var}Api.update(record.id, {{ {key} }})"

    def card_paths(self, view: CardsView | BoardView) -> list[str]:
        """Return the field paths that the cards of a view show."""
        card = view.card
        display = definition_display(self.definition.entities[view.entity])
        paths = [card.title if card and card.title else display]
        if card is not None:
            paths += [p for p in (card.subtitle,) if p]
            paths += [card.badge.field] if card.badge else []
            paths += [*card.fields, *card.footer]
        if isinstance(view, BoardView):
            paths.append(view.group_by)
        return paths

    def lookups_of(self, entity: str, paths: Iterable[str]) -> set[str]:
        """Return the related entities that the field paths of an entity go through."""
        return self._lookups(entity, paths)

    def action_plans(
        self, entity: str, actions: Iterable[tuple[str, Action]], scope: str
    ) -> list[ActionPlan]:
        """Return the plans of the actions that the templates can render.

        The scope is `view` (no record), `row` (one record), or `bulk`.
        """
        return self._actions(entity, actions, scope)

    def form_refs(self, actions: Iterable[ActionPlan]) -> list[FormRef]:
        """Return the forms that actions open in a dialog or a sheet, in order."""
        refs: list[FormRef] = []
        for form_name in dict.fromkeys(a.form for a in actions if a.form):
            form_plan = self.forms.plan(form_name)
            refs.append(
                FormRef(
                    form_name,
                    form_plan.component,
                    form_plan.module,
                    form_plan.needs_record,
                    form_plan.route_params,
                )
            )
        return refs

    def _lookups(self, entity: str, paths: Iterable[str]) -> set[str]:
        found: set[str] = set()
        for path in paths:
            current = entity
            for segment in path.split("."):
                relation = self.definition.entities[current].relations.get(segment)
                if relation is None:
                    break
                found.add(relation.target)
                current = relation.target
        return found

    def _filter(self, entity: str, name: str, filter_: Filter) -> FilterPlan:
        key = camel(name)
        state = f"filters.{key}"
        if isinstance(filter_, SearchFilter):
            texts = [self.value(entity, path).text_expr for path in filter_.fields]
            default = filter_.default if isinstance(filter_.default, str) else ""
            return FilterPlan(
                name=name,
                key=key,
                element_id=filter_.id,
                kind="search",
                label=filter_.label or "Search",
                default=js(default),
                state_type="string",
                match=f"matchesSearch({state}, [{', '.join(texts)}])",
            )
        value = self.value(entity, filter_.field)
        filter_label = filter_.label or value.label
        if isinstance(filter_, BooleanFilter):
            return FilterPlan(
                name=name,
                key=key,
                element_id=filter_.id,
                kind="boolean",
                label=filter_label,
                default=js(bool(filter_.default)),
                state_type="boolean",
                match=f"!{state} || {value.expr} === true",
                value=value,
            )
        if isinstance(filter_, DateRangeFilter):
            return FilterPlan(
                name=name,
                key=key,
                element_id=filter_.id,
                kind="date_range",
                label=filter_label,
                default="{}",
                state_type="DateRange",
                match=f"inDateRange({value.expr}, {state})",
                value=value,
            )
        assert isinstance(filter_, SelectFilter)
        options = self._options(value)
        if filter_.multiple:
            defaults = filter_.default if isinstance(filter_.default, list) else []
            default = js([str(item) for item in defaults if item is not None])
            if value.kind == "many":
                some = f"{value.key_expr}.some((id) => {state}.includes(id))"
                match = f"{state}.length === 0 || {some}"
            else:
                match = f"{state}.length === 0 || {state}.includes(String({value.key_expr}))"
            return FilterPlan(
                name=name,
                key=key,
                element_id=filter_.id,
                kind="select",
                label=filter_label,
                default=default,
                state_type="string[]",
                match=match,
                value=value,
                multiple=True,
                options=options,
            )
        default_value = filter_.default
        default = js(str(default_value)) if isinstance(default_value, str | int) else "null"
        if value.kind == "many":
            match = f"{state} === null || {value.key_expr}.includes({state})"
        else:
            match = f"{state} === null || String({value.key_expr}) === {state}"
        return FilterPlan(
            name=name,
            key=key,
            element_id=filter_.id,
            kind="select",
            label=filter_label,
            default=default,
            state_type="string | null",
            match=match,
            value=value,
            options=options,
        )

    def _options(self, value: Value) -> str:
        if value.target is not None:
            display = self.display_field(value.target)
            return (
                f"[...lookups.{camel(value.target)}.values()].map((item) => "
                f'({{ value: item.id, label: String(item.{display} ?? "") }}))'
            )
        if value.badge:
            return f"badgeOptions(badges.{value.badge})"
        if value.type == "boolean":
            return '[{ value: "true", label: "Yes" }, { value: "false", label: "No" }]'
        items = [f"{{ value: {js(v)}, label: {js(label(v))} }}" for v in value.enum_values]
        return "[" + ", ".join(items) + "]"

    def _actions(
        self, entity: str, actions: Iterable[tuple[str, Action]], scope: str
    ) -> list[ActionPlan]:
        result: list[ActionPlan] = []
        for name, action in actions:
            plan = self._action(entity, name, action, scope)
            if plan is not None:
                result.append(plan)
        return result

    def _action(self, entity: str, name: str, action: Action, scope: str) -> ActionPlan | None:
        """Return the plan of an action, or None if the view cannot run it.

        An action of a view (not of a row) has no record, so it can only
        open a page without parameters, open a create form, or run a custom
        action. A form action opens the page of the form, or the form in a
        dialog or a sheet. A bulk action cannot open a form.
        """
        definition = self.definition
        action_label = action.label or label(name)
        record = scope in ("row", "bulk")
        common: dict[str, Any] = {
            "name": name,
            "element_id": action.id,
            "action": action,
            "label": action_label,
        }
        if isinstance(action, NavigateAction):
            page = definition.pages[action.page]
            if _path_params(page.path) and not record:
                return None
            href = self.href(entity, action.page, action.params, "record")
            return ActionPlan(**common, href=href)
        if isinstance(action, OperationAction):
            if not record:
                return None
            operation = definition.operations[action.operation]
            op = camel(action.operation)
            if operation.kind == "delete" or (operation.kind == "custom" and not operation.params):
                module = (
                    f"@/features/{_kebab(action.operation)}"
                    if operation.kind == "custom"
                    else f"@/entities/{_kebab(operation.entity)}"
                )
                on_success = action.on_success
                target = on_success.navigate if on_success else None
                navigate_to = (
                    f"pageHref({js(camel(target))})"
                    if target and not _path_params(definition.pages[target].path)
                    else None
                )
                return ActionPlan(
                    **common,
                    run=f"Promise.all(records.map((record) => {op}(record.id)))",
                    navigate_to=navigate_to,
                    imports=(f'import {{ {op} }} from "{module}";',),
                )
            return None
        if isinstance(action, FormAction):
            if not self.with_forms:
                return None
            form = self.forms.plan(action.form)
            if scope == "bulk" or (form.needs_record and not record):
                return None
            if form.page_href is not None:
                return ActionPlan(**common, href=form.page_href)
            return ActionPlan(**common, form=action.form)
        if action.kind == "custom":
            gap = gap_path(definition, action.id)
            function = gap[1]
            if scope == "bulk":
                call = f"{function}(records)"
            elif record:
                call = f"Promise.all(records.map((record) => {function}(record)))"
            else:
                call = f"{function}()"
            return ActionPlan(
                **common,
                run=call,
                imports=(f'import {{ {function} }} from "@/{gap[0]}.gen";',),
            )
        return None


def _value_parts(code: str) -> set[str]:
    """Return the value components that JSX code uses."""
    names = {"badge": "<BadgeValue", "avatar": "<AvatarValue", "formatted": "<FormattedValue"}
    return {part for part, tag in names.items() if tag in code}


def _badge_name(camel_name: str | None, sets: dict[str, BadgeSet]) -> str | None:
    return next((name for name in sets if camel(name) == camel_name), None)


def definition_display(entity: Entity) -> str:
    """Return the field that names a record: the display field, else the first string field.

    An entity without a string field gives `id`.
    """
    if entity.display_field:
        return entity.display_field
    return next((name for name, f in entity.fields.items() if f.type == "string"), "id")


def gap_path(definition: AppDefinition, element_id: str) -> tuple[str, str]:
    """Return the module path below `src/` and the function name of a custom action gap."""
    spec = gap_spec(definition, element_id, "custom_action")
    return spec.base.removeprefix("src/"), spec.name


def _action_key(action: Action) -> tuple[str, str] | None:
    """Return the kind and the target of an action, to find the same action in two places."""
    if isinstance(action, FormAction):
        return ("form", action.form)
    if isinstance(action, OperationAction):
        return ("operation", action.operation)
    if isinstance(action, NavigateAction):
        return ("navigate", action.page)
    return None


def _path_params(path: str) -> list[str]:
    return [part[1:-1] for part in path.split("/") if part.startswith("{")]


def _kebab(name: str) -> str:
    return "-".join(words(name))


def state_ids(definition: AppDefinition, view: View | None) -> list[str]:
    """Return the element IDs of the states that a view shows, for the traces.

    Without a view, return the IDs of the default states.
    """
    ids: list[str] = []
    defaults = definition.ui.defaults if definition.ui else None
    for states in (view.states if view else None, defaults.states if defaults else None):
        if states is None:
            continue
        ids.append(states.id)
        ids += [s.id for s in (states.loading, states.empty, states.error) if s is not None]
    return ids


def badge_color(ref: str | None) -> str | None:
    """Return the CSS value of the color token of a badge value."""
    return css_var(ref) if ref else None


def grid_classes(grid: Grid | None, columns: int = 1) -> str:
    """Return the Tailwind CSS classes of a grid with its responsive overrides.

    The overrides apply below each breakpoint, and the smallest breakpoint
    wins: Tailwind CSS sorts the `max-*` variants from the largest.
    """
    if grid is None:
        return f"grid grid-cols-{columns} gap-4"
    classes = ["grid", f"grid-cols-{grid.columns}"]
    classes.append(f"gap-{css_class_var(grid.gap)}" if grid.gap else "gap-4")
    for breakpoint, override in grid.responsive.items():
        if override.columns:
            classes.append(f"max-{breakpoint}:grid-cols-{override.columns}")
        if override.gap:
            classes.append(f"max-{breakpoint}:gap-{css_class_var(override.gap)}")
    return " ".join(classes)


def lookups_param(code: str) -> str:
    """Return the name of the `lookups` parameter: `_lookups` if the code does not use it."""
    return "lookups" if "lookups." in code else "_lookups"


HELPERS: dict[str, Callable[..., Any]] = {
    "lookups_param": lookups_param,
    "badge_color": badge_color,
    "grid_classes": grid_classes,
}
"""The helpers of the view templates."""


_VIEW = "src/widgets/{{ name | kebab }}"


def view_rules() -> tuple[Output, ...]:
    """Return the output rules of the views, the dashboards, and the action bars.

    Each view (a table, a card list, a board, or a detail view) and each
    dashboard is a widget. The actions of a page header are a widget in
    `src/widgets/page-actions`, and the actions of a top bar are a part of
    its layout widget. The runtime files of the views are in the app
    only if a view needs them. The bindings that use the views put
    `ViewContext` in their context as `ui_views`, and the view helpers
    (`HELPERS`) in their helpers.
    """
    return (
        *(
            Output(template=f"ui/views/{template}", path=path, when=when)
            for template, path, when in (
                ("lib/format.ts.j2", "src/shared/lib/format.ts", "ui_views.runtime"),
                ("lib/query.ts.j2", "src/shared/lib/query.ts", "ui_views.runtime"),
                ("lib/badges.ts.j2", "src/shared/config/badges.ts", "ui_views.runtime"),
                ("ui/actions.tsx.j2", "src/shared/ui/actions.tsx", "ui_views.runtime"),
                ("ui/view-state.tsx.j2", "src/shared/ui/view-state.tsx", "ui_views.runtime"),
                (
                    "ui/list-pagination.tsx.j2",
                    "src/shared/ui/list-pagination.tsx",
                    "'table' in ui_views.features or 'cards' in ui_views.features",
                ),
                (
                    "ui/data-table.tsx.j2",
                    "src/shared/ui/data-table.tsx",
                    "'table' in ui_views.features",
                ),
                *(
                    (f"{folder}/{part}.tsx.j2", f"src/shared/ui/{folder}/{part}.tsx", when)
                    for folder, part, when in (
                        ("values", "badge-value", "'badge' in ui_views.features"),
                        ("values", "avatar-value", "'avatar' in ui_views.features"),
                        ("values", "formatted-value", "'formatted' in ui_views.features"),
                        ("filters", "search-filter", "'search' in ui_views.features"),
                        ("filters", "boolean-filter", "'boolean' in ui_views.features"),
                        ("filters", "date-range-filter", "'date_range' in ui_views.features"),
                        ("filters", "select-filter", "'select' in ui_views.features"),
                        ("filters", "multi-select-filter", "'multi_select' in ui_views.features"),
                    )
                ),
            )
        ),
        *(
            Output(
                template=f"ui/views/{kind}-view.tsx.j2",
                path=_VIEW + "/ui/{{ name | kebab }}-view.tsx",
                for_each=f"{kind}_view",
            )
            for kind in ("table", "cards", "board")
        ),
        *(
            Output(
                template="ui/views/index.ts.j2", path=_VIEW + "/index.ts", for_each=f"{kind}_view"
            )
            for kind in ("table", "cards", "board", "detail")
        ),
        Output(
            template="ui/details/detail-view.tsx.j2",
            path=_VIEW + "/ui/{{ name | kebab }}-view.tsx",
            for_each="detail_view",
        ),
        *(
            Output(template=f"ui/dashboards/{template}", path=path, when=when)
            for template, path, when in (
                ("lib/aggregate.ts.j2", "src/shared/lib/aggregate.ts", "ui_views.dashboards"),
                ("ui/widget-card.tsx.j2", "src/shared/ui/widget-card.tsx", "ui_views.dashboards"),
                (
                    "ui/dashboard-chart.tsx.j2",
                    "src/shared/ui/dashboard-chart.tsx",
                    "'chart' in ui_views.features",
                ),
            )
        ),
        Output(
            template="ui/dashboards/dashboard.tsx.j2",
            path=_VIEW + "/ui/{{ name | kebab }}-dashboard.tsx",
            for_each="dashboard",
        ),
        Output(
            template="ui/dashboards/index.ts.j2", path=_VIEW + "/index.ts", for_each="dashboard"
        ),
        Output(
            template="ui/widgets/actions/action-bar.tsx.j2",
            path="src/widgets/page-actions/ui/{{ name | kebab }}-actions.tsx",
            for_each="page",
            when="ui_views.action_bar(element_id).actions",
        ),
        Output(
            template="ui/widgets/actions/index.ts.j2",
            path="src/widgets/page-actions/index.ts",
            when="ui_views.page_action_bars",
        ),
        Output(
            template="ui/widgets/actions/action-bar.tsx.j2",
            path="src/widgets/layouts/ui/{{ element_id.split('.')[2] | kebab }}-topbar-actions.tsx",
            for_each="topbar",
            when="ui_views.action_bar(element_id).actions",
        ),
    )
