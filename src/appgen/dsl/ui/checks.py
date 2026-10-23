"""Checks of the UI part of an app definition (ADR 0003).

The validator runs these checks after the checks of the data part.
"""

import difflib
import re
from collections.abc import Collection, Generator, Iterable, Iterator, Mapping
from typing import cast

from appgen.dsl.diagnostics import Diagnostic, Location
from appgen.dsl.element import Element
from appgen.dsl.model import AppDefinition, Field
from appgen.dsl.ui.common import State, States
from appgen.dsl.ui.dashboards import (
    FILTER_OPS,
    RELATIVE_DATES,
    ChartWidget,
    CustomWidget,
    ListWidget,
    StatWidget,
    Widget,
)
from appgen.dsl.ui.fields import (
    DATE_TYPES,
    NUMBER_TYPES,
    SINGLE_KINDS,
    TEXT_TYPES,
    WIDGET_TYPES,
    FieldPathError,
    FieldTarget,
    default_widget,
    member_names,
    resolve_path,
)
from appgen.dsl.ui.forms import CompareRule, Form, FormField
from appgen.dsl.ui.tokens import check_tokens
from appgen.dsl.ui.views import (
    BadgeRef,
    BadgeSet,
    BoardView,
    BooleanFilter,
    Card,
    CardsView,
    Column,
    DateRangeFilter,
    DetailView,
    Filter,
    SearchFilter,
    SelectFilter,
    TableView,
    View,
)

FORMAT_TYPES: dict[str, frozenset[str] | None] = {
    "text": None,
    "number": NUMBER_TYPES,
    "currency": NUMBER_TYPES,
    "percent": NUMBER_TYPES,
    "date": DATE_TYPES,
    "datetime": frozenset({"datetime"}),
    "relative_time": DATE_TYPES,
    "boolean": frozenset({"boolean"}),
    "badge": frozenset({"enum"}),
    "email": frozenset({"email"}),
    "url": frozenset({"url"}),
    "avatar": SINGLE_KINDS,
}
"""The field types (and relation kinds) that each column format suits. None: all."""

MANY_KINDS = frozenset({"one_to_many", "many_to_many"})
STRING_TYPES = frozenset({"string", "text", "email", "url"})
FORM_OPERATION_KINDS = ("create", "update", "custom")
ROUTE_DEFAULT = re.compile(r"^\$route\.[a-z][a-z0-9_]*$")


def check_ui_tokens(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The design tokens must have valid names, types, values, and references."""
    if definition.ui is not None:
        yield from check_tokens(definition.ui.tokens)


def check_ui_views(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Badges and views must refer to entities and fields that exist and suit them."""
    if definition.ui is None:
        return
    for badge in definition.ui.badges.values():
        yield from _check_badge_set(definition, badge)
    for view in definition.ui.views.values():
        yield from _check_view(definition, view)


def check_ui_forms(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Forms must call a suitable operation, and each form field must suit its widget."""
    if definition.ui is None:
        return
    for form in definition.ui.forms.values():
        yield from _check_form(definition, form)


def _check_form(definition: AppDefinition, form: Form) -> Iterator[Diagnostic]:
    if form.entity not in definition.entities:
        yield _missing(form, "entity", "entity", form.entity, definition.entities)
        return
    params: dict[str, Field] | None = None
    operation = definition.operations.get(form.operation)
    if operation is None:
        yield _missing(form, "operation", "operation", form.operation, definition.operations)
    elif operation.entity != form.entity or operation.kind not in FORM_OPERATION_KINDS:
        yield _error(
            "unsuitable-operation",
            f"A form on '{form.entity}' needs a create, update, or custom operation on "
            f"'{form.entity}', but '{form.operation}' is a {operation.kind} operation on "
            f"'{operation.entity}'.",
            form,
            at="operation",
        )
    elif operation.kind == "custom":
        params = dict(operation.params)
    for name, field in form.fields.items():
        target = yield from _form_target(definition, form, params, field, name)
        if target is not None:
            yield from _check_form_field(field, target)
    yield from _check_form_sections(form)
    for rule in form.rules.values():
        if isinstance(rule, CompareRule):
            for key in ("field", "other"):
                name = getattr(rule, key)
                if name not in form.fields:
                    yield _missing(rule, key, "form field", name, form.fields)
    for name, value in form.defaults.items():
        if name not in form.fields:
            yield from _form_target(definition, form, params, form, name, at="defaults")
        if isinstance(value, str) and value.startswith("$") and not ROUTE_DEFAULT.match(value):
            yield _error(
                "invalid-value",
                f"The default {value!r} is not valid. Write a literal, or $route.<param>.",
                form,
                at="defaults",
            )


def _form_target(
    definition: AppDefinition,
    form: Form,
    params: dict[str, Field] | None,
    element: Element,
    name: str,
    at: str | None = None,
) -> Generator[Diagnostic, None, FieldTarget | None]:
    """Yield an error if a form field name is not a field, relation, or parameter."""
    if params is not None:
        if name in params:
            return FieldTarget(form.operation, name, params[name])
        yield _missing(element, at, "parameter", name, params)
        return None
    if name == "id":
        yield _error("unsuitable-field", "A form cannot set the primary key 'id'.", element, at=at)
        return None
    return (yield from _resolve(definition, element, at, form.entity, name))


def _check_form_field(field: FormField, target: FieldTarget) -> Iterator[Diagnostic]:
    widget = field.widget or default_widget(target)
    if widget is None:
        shown = target.relation_kind or target.type
        yield _error(
            "missing-widget",
            f"The field '{target.entity}.{target.name}' ({shown}) has no default widget.",
            field,
            hint="Set 'widget: custom' and write the widget by hand.",
        )
        return
    yield from _check_suits(field, "widget", f"The widget '{widget}'", target, WIDGET_TYPES[widget])
    if field.rules is None:
        return
    for key, types in (
        ("min_length", STRING_TYPES),
        ("max_length", STRING_TYPES),
        ("pattern", STRING_TYPES),
        ("min", NUMBER_TYPES),
        ("max", NUMBER_TYPES),
    ):
        if getattr(field.rules, key) is not None:
            yield from _check_suits(field.rules, key, f"The rule '{key}'", target, types)


def _check_form_sections(form: Form) -> Iterator[Diagnostic]:
    placed: dict[str, str] = {}
    for section_name, section in form.sections.items():
        for name in section.fields:
            if name not in form.fields:
                yield _missing(section, "fields", "form field", name, form.fields)
            elif name in placed:
                yield _error(
                    "duplicate-name",
                    f"The form field '{name}' is in the sections '{placed[name]}' and "
                    f"'{section_name}'. A field can be in one section only.",
                    section,
                    at="fields",
                )
            else:
                placed[name] = section_name


def _check_badge_set(definition: AppDefinition, badge: BadgeSet) -> Iterator[Diagnostic]:
    entity, _, name = badge.field.partition(".")
    if entity not in definition.entities:
        yield _missing(badge, "field", "entity", entity, definition.entities)
        return
    target = yield from _resolve(definition, badge, "field", entity, name)
    if target is None:
        return
    if target.type != "enum":
        yield _error(
            "unsuitable-field",
            f"A badge set needs an enum field, but '{badge.field}' has the type '{target.type}'.",
            badge,
            at="field",
        )
        return
    for value, item in badge.values.items():
        if value not in target.enum_values:
            yield _missing(item, None, "enum value", value, target.enum_values)


def _check_view(definition: AppDefinition, view: View) -> Iterator[Diagnostic]:
    if view.entity not in definition.entities:
        yield _missing(view, "entity", "entity", view.entity, definition.entities)
        return
    entity = view.entity
    if view.states is not None:
        yield from _check_states(view.states, view.actions)
    if not isinstance(view, DetailView) and view.sort is not None:
        yield from _check_paths(definition, view.sort, "field", entity, [view.sort.field])
    match view:
        case TableView():
            for name, column in view.columns.items():
                yield from _check_column(definition, entity, name, column)
            for filter_ in view.filters.values():
                yield from _check_filter(definition, entity, filter_)
            if view.row_click is not None and view.row_click not in view.row_actions:
                yield _missing(view, "row_click", "row action", view.row_click, view.row_actions)
            if view.bulk_actions and not view.selection:
                yield _error(
                    "missing-selection",
                    "Bulk actions need 'selection: true'.",
                    view,
                    at="bulk_actions",
                    hint="Add 'selection: true' to the view.",
                )
        case CardsView():
            for filter_ in view.filters.values():
                yield from _check_filter(definition, entity, filter_)
            if view.card is not None:
                yield from _check_card(definition, entity, view.card)
        case BoardView():
            yield from _check_board(definition, entity, view)
        case DetailView():
            yield from _check_detail(definition, entity, view)


def _check_detail(definition: AppDefinition, entity: str, view: DetailView) -> Iterator[Diagnostic]:
    if view.header is not None:
        header = view.header
        for key in ("title", "subtitle"):
            path = getattr(header, key)
            if path is not None:
                yield from _check_paths(definition, header, key, entity, [path])
        for path in header.badges:
            target = yield from _resolve(definition, header, "badges", entity, path)
            if target is not None:
                yield from _check_suits(header, "badges", "A badge", target, FORMAT_TYPES["badge"])
    sections = list(view.sections.values())
    for tab in view.tabs.values():
        sections += tab.sections.values()
        if tab.relation is not None and tab.view is not None:
            yield from _check_related_tab(definition, entity, tab.relation, tab.view, tab)
    for section in sections:
        yield from _check_paths(definition, section, "fields", entity, section.fields)


def _check_related_tab(
    definition: AppDefinition, entity: str, relation_name: str, view_name: str, tab: Element
) -> Iterator[Diagnostic]:
    relations = definition.entities[entity].relations
    relation = relations.get(relation_name)
    if relation is None:
        yield _missing(tab, "relation", "relation", relation_name, relations)
        return
    if relation.kind not in MANY_KINDS:
        yield _error(
            "unsuitable-field",
            f"A tab lists related records of a one_to_many or many_to_many relation, but "
            f"'{entity}.{relation_name}' is {relation.kind}.",
            tab,
            at="relation",
        )
        return
    views = definition.ui.views if definition.ui else {}
    yield from _check_list_view(views, tab, "view", view_name, relation.target)


def _check_list_view(
    views: Mapping[str, View], element: Element, key: str, name: str, entity: str | None
) -> Iterator[Diagnostic]:
    """A view that shows a list must be a table or a card list (of an entity, if given)."""
    view = views.get(name)
    if view is None:
        yield _missing(element, key, "view", name, views)
    elif not isinstance(view, TableView | CardsView):
        yield _error(
            "unsuitable-view",
            f"The view '{name}' is a {view.kind} view. A list needs a table or a card list.",
            element,
            at=key,
        )
    elif entity is not None and view.entity != entity:
        yield _error(
            "unsuitable-view",
            f"The view '{name}' shows '{view.entity}', but this list shows '{entity}'.",
            element,
            at=key,
        )


def check_ui_dashboards(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Dashboard widgets must refer to entities, fields, and views that exist and suit them."""
    if definition.ui is None:
        return
    for dashboard in definition.ui.dashboards.values():
        for widget in dashboard.widgets.values():
            yield from _check_widget(definition, widget)


def _check_widget(definition: AppDefinition, widget: Widget) -> Iterator[Diagnostic]:
    match widget:
        case StatWidget() | ChartWidget():
            if widget.entity not in definition.entities:
                yield _missing(widget, "entity", "entity", widget.entity, definition.entities)
                return
            yield from _check_aggregate(definition, widget)
            yield from _check_record_filter(definition, widget, widget.entity, widget.filter)
            if isinstance(widget, ChartWidget):
                yield from _check_chart_group(definition, widget)
        case ListWidget():
            views = definition.ui.views if definition.ui else {}
            yield from _check_list_view(views, widget, "view", widget.view, None)
            view = views.get(widget.view)
            if isinstance(view, TableView | CardsView) and view.entity in definition.entities:
                yield from _check_record_filter(definition, widget, view.entity, widget.filter)
                if widget.sort is not None:
                    yield from _check_paths(
                        definition, widget.sort, "field", view.entity, [widget.sort.field]
                    )
        case CustomWidget():
            pass


def _check_aggregate(
    definition: AppDefinition, widget: StatWidget | ChartWidget
) -> Iterator[Diagnostic]:
    if widget.aggregate == "count":
        if widget.field is not None:
            yield _error(
                "invalid-value",
                "A count needs no field.",
                widget,
                at="field",
                hint="Remove the key 'field', or use another aggregate, for example sum.",
            )
        return
    if widget.field is None:
        yield _error(
            "missing-key",
            f"The aggregate '{widget.aggregate}' needs a number field.",
            widget,
            hint="Add the key 'field'.",
        )
        return
    target = yield from _resolve(definition, widget, "field", widget.entity, widget.field)
    if target is not None:
        what = f"The aggregate '{widget.aggregate}'"
        yield from _check_suits(widget, "field", what, target, NUMBER_TYPES)


def _check_chart_group(definition: AppDefinition, widget: ChartWidget) -> Iterator[Diagnostic]:
    target = yield from _resolve(definition, widget, "group_by", widget.entity, widget.group_by)
    if target is None:
        return
    types = frozenset({"enum", *DATE_TYPES, *SINGLE_KINDS})
    yield from _check_suits(widget, "group_by", "A chart group", target, types)
    if widget.badge is not None and target.type == "enum":
        yield from _check_badge_ref(definition, widget, widget.badge, target)


def _check_record_filter(
    definition: AppDefinition, element: Element, entity: str, record_filter: Mapping[str, object]
) -> Iterator[Diagnostic]:
    for path, condition in record_filter.items():
        target = yield from _resolve(definition, element, "filter", entity, path)
        if target is None:
            continue
        conditions: dict[str, object] = (
            cast(dict[str, object], condition) if isinstance(condition, dict) else {"eq": condition}
        )
        for op, value in conditions.items():
            if op not in FILTER_OPS:
                yield _missing(element, "filter", "filter operator", op, FILTER_OPS)
                continue
            values = cast(list[object], value) if isinstance(value, list) else [value]
            for item in values:
                yield from _check_filter_value(element, target, item)


def _check_filter_value(
    element: Element, target: FieldTarget, value: object
) -> Iterator[Diagnostic]:
    if isinstance(value, str) and value.startswith("$"):
        if value not in RELATIVE_DATES or target.type not in DATE_TYPES:
            yield _error(
                "invalid-value",
                f"The filter value {value!r} is not valid for the field "
                f"'{target.entity}.{target.name}' ({target.type}).",
                element,
                at="filter",
                hint="Use $today or $now only for date and datetime fields.",
            )
    elif target.enum_values and value not in target.enum_values:
        yield _missing(element, "filter", "enum value", str(value), target.enum_values)


def check_ui_states(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The default states can only use the action `retry`, in the error state."""
    if definition.ui is not None and definition.ui.defaults is not None:
        states = definition.ui.defaults.states
        if states is not None:
            yield from _check_states(states, {})


def _check_states(states: States, actions: Mapping[str, object]) -> Iterator[Diagnostic]:
    """The action of a state must be an action of the view, or `retry` for an error."""
    for key in ("loading", "empty", "error"):
        state: State | None = getattr(states, key)
        if state is None or state.action is None or state.action in actions:
            continue
        if key == "error" and state.action == "retry":
            continue
        choices = [*actions, "retry"] if key == "error" else list(actions)
        yield _missing(state, "action", "action", state.action, choices)


def _check_board(definition: AppDefinition, entity: str, view: BoardView) -> Iterator[Diagnostic]:
    if view.card is not None:
        yield from _check_card(definition, entity, view.card)
    target = yield from _resolve(definition, view, "group_by", entity, view.group_by)
    if target is None:
        return
    if target.type != "enum":
        yield _error(
            "unsuitable-field",
            f"A board groups by an enum field, but '{view.group_by}' has the type '{target.type}'.",
            view,
            at="group_by",
        )
        return
    for value, column in view.columns.items():
        if value not in target.enum_values:
            yield _missing(column, None, "enum value", value, target.enum_values)


def _check_column(
    definition: AppDefinition, entity: str, name: str, column: Column
) -> Iterator[Diagnostic]:
    path = column.field or name
    target = yield from _resolve(
        definition, column, "field" if column.field else None, entity, path
    )
    if target is None:
        return
    if column.format is not None:
        yield from _check_suits(
            column, "format", f"The format '{column.format}'", target, FORMAT_TYPES[column.format]
        )
    if column.badge is not None:
        yield from _check_badge_ref(definition, column, column.badge, target)


def _check_card(definition: AppDefinition, entity: str, card: Card) -> Iterator[Diagnostic]:
    for key in ("title", "subtitle"):
        path = getattr(card, key)
        if path is not None:
            yield from _check_paths(definition, card, key, entity, [path])
    yield from _check_paths(definition, card, "fields", entity, card.fields)
    yield from _check_paths(definition, card, "footer", entity, card.footer)
    if card.badge is not None:
        yield from _check_badge_field(definition, entity, card.badge)


def _check_badge_field(
    definition: AppDefinition, entity: str, ref: BadgeRef
) -> Iterator[Diagnostic]:
    target = yield from _resolve(definition, ref, "field", entity, ref.field)
    if target is None:
        return
    yield from _check_suits(ref, "field", "A badge", target, FORMAT_TYPES["badge"])
    if ref.badge is not None and target.type == "enum":
        yield from _check_badge_ref(definition, ref, ref.badge, target)


def _check_badge_ref(
    definition: AppDefinition, element: Element, name: str, target: FieldTarget
) -> Iterator[Diagnostic]:
    badges = definition.ui.badges if definition.ui else {}
    badge = badges.get(name)
    if badge is None:
        yield _missing(element, "badge", "badge set", name, badges)
    elif badge.field != f"{target.entity}.{target.name}" and _is_enum(definition, badge.field):
        yield _error(
            "unsuitable-badge",
            f"The badge set '{name}' is for the field '{badge.field}', "
            f"not for '{target.entity}.{target.name}'.",
            element,
            at="badge",
        )


def _is_enum(definition: AppDefinition, field: str) -> bool:
    """Return true if `<Entity>.<field>` is an enum field."""
    entity, _, name = field.partition(".")
    try:
        return resolve_path(definition, entity, name).type == "enum"
    except FieldPathError:
        return False


def _check_filter(definition: AppDefinition, entity: str, filter_: Filter) -> Iterator[Diagnostic]:
    match filter_:
        case SearchFilter():
            for path in filter_.fields:
                target = yield from _resolve(definition, filter_, "fields", entity, path)
                if target is not None:
                    yield from _check_suits(
                        filter_, "fields", "A search filter", target, TEXT_TYPES
                    )
            return
        case SelectFilter():
            types = frozenset({"enum", *SINGLE_KINDS, "many_to_many"})
        case BooleanFilter():
            types = frozenset({"boolean"})
        case DateRangeFilter():
            types = DATE_TYPES
    target = yield from _resolve(definition, filter_, "field", entity, filter_.field)
    if target is not None:
        yield from _check_suits(filter_, "field", f"A {filter_.kind} filter", target, types)


def _check_paths(
    definition: AppDefinition, element: Element, key: str, entity: str, paths: Iterable[str]
) -> Iterator[Diagnostic]:
    for path in paths:
        yield from _resolve(definition, element, key, entity, path)


def _resolve(
    definition: AppDefinition, element: Element, key: str | None, entity: str, path: str
) -> Generator[Diagnostic, None, FieldTarget | None]:
    """Yield an error if a field path does not resolve. Return its target, or None.

    Use it with `yield from`, which gives the return value.
    """
    try:
        return resolve_path(definition, entity, path)
    except FieldPathError as error:
        last = path.rpartition(".")[2]
        matches = difflib.get_close_matches(last, member_names(definition, entity), n=1)
        yield _error(
            "unknown-reference",
            str(error),
            element,
            at=key,
            hint=f"Did you mean '{matches[0]}'?" if matches and "." not in path else None,
        )
        return None


def _check_suits(
    element: Element,
    key: str,
    what: str,
    target: FieldTarget,
    types: Collection[str] | None,
) -> Iterator[Diagnostic]:
    if types is None or target.is_one_of(types):
        return
    shown = target.relation_kind or target.type
    yield _error(
        "unsuitable-field",
        f"{what} does not suit the field '{target.entity}.{target.name}' ({shown}). "
        f"It needs one of: {', '.join(sorted(types))}.",
        element,
        at=key,
    )


def _missing(
    element: Element, key: str | None, what: str, name: str, choices: Iterable[str]
) -> Diagnostic:
    matches = difflib.get_close_matches(name, list(choices), n=1)
    return _error(
        "unknown-reference",
        f"The {what} '{name}' does not exist.",
        element,
        at=key,
        hint=f"Did you mean '{matches[0]}'?" if matches else None,
    )


def _error(
    code: str, message: str, element: Element, *, at: str | None = None, hint: str | None = None
) -> Diagnostic:
    location = element.location_of(at) if at else element.location
    return Diagnostic(
        code=code,
        message=message,
        location=location or Location("<unknown>", 1, 1),
        element_id=element.id or None,
        hint=hint,
    )
