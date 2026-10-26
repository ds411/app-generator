"""Checks of the UI part of an app definition (ADR 0003).

The validator runs these checks after the checks of the data part.
"""

import difflib
import json
import re
from collections.abc import Collection, Generator, Iterable, Iterator, Mapping
from typing import cast

from appgen.dsl.diagnostics import Diagnostic, Location
from appgen.dsl.element import Element
from appgen.dsl.model import AppDefinition, Field, Operation, Page, Relation
from appgen.dsl.openapi import accepts, object_properties, property_chain, query_value
from appgen.dsl.storage import FILE_TYPES
from appgen.dsl.ui.api_data import api_data
from appgen.dsl.ui.common import (
    ActionBase,
    FormAction,
    Grid,
    NavigateAction,
    OperationAction,
    State,
    States,
)
from appgen.dsl.ui.dashboards import (
    FILTER_OPS,
    RELATIVE_DATES,
    ChartWidget,
    CustomWidget,
    ListWidget,
    StatWidget,
    Widget,
    currency_path,
    single_value,
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
from appgen.dsl.ui.layout import Layout, Sidebar
from appgen.dsl.ui.model import Defaults
from appgen.dsl.ui.page import PageContent
from appgen.dsl.ui.tokens import TokenTable, check_tokens
from appgen.dsl.ui.views import (
    ApiCardsView,
    ApiDetailView,
    ApiListViewBase,
    ApiTableView,
    ApiView,
    ApiViewBase,
    BadgeRef,
    BadgeSet,
    BoardView,
    BooleanFilter,
    CalendarView,
    Card,
    CardsView,
    Column,
    DateRangeFilter,
    DetailView,
    Filter,
    ListViewBase,
    Pagination,
    SearchFilter,
    SelectFilter,
    TableView,
    View,
    ViewResponsive,
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
    "avatar": SINGLE_KINDS | {"image"},
}
"""The field types (and relation kinds) that each column format suits. None: all."""

IMAGE_TYPES = frozenset({"image"})

MANY_KINDS = frozenset({"one_to_many", "many_to_many"})
STRING_TYPES = frozenset({"string", "text", "email", "url"})
FORM_OPERATION_KINDS = ("create", "update", "custom")
ROUTE_DEFAULT = re.compile(r"^\$route\.[a-z][a-z0-9_]*$")
ROUTE_PARAM = re.compile(r"^\$route\.([a-z][a-z0-9_]*)$")
"""A path parameter of the page as the value of a parameter of an API view."""


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
        if isinstance(view, ListViewBase | ApiListViewBase) and view.pagination is not None:
            yield from _check_pagination(view, view.pagination)


def _check_pagination(
    view: ListViewBase | ApiListViewBase, pagination: Pagination
) -> Iterator[Diagnostic]:
    """A list that scrolls is a table or a card list of an entity, without page sizes."""
    if pagination.mode != "scroll":
        return
    if isinstance(view, ApiListViewBase):
        yield _error(
            "invalid-option",
            "The mode 'scroll' is for the tables and the card lists of entities.",
            pagination,
            at="mode",
            hint="Remove 'mode', or use 'mode: pages'.",
        )
    elif pagination.page_sizes:
        yield _error(
            "invalid-option",
            "'page_sizes' is not for the mode 'scroll': the list loads 'page_size' records "
            "at a time.",
            pagination,
            at="page_sizes",
            hint="Remove 'page_sizes'.",
        )


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
            yield from _check_lines_field(definition, form, operation, field, target)
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
    if isinstance(target.member, Field) and target.member.computed is not None:
        yield _error(
            "unsuitable-field",
            f"The field '{target.entity}.{target.name}' is computed. A form cannot change it.",
            field,
            hint="Remove the field from the form.",
        )
        return
    if isinstance(target.member, Field) and target.member.sequence is not None:
        yield _error(
            "unsuitable-field",
            f"The field '{target.entity}.{target.name}' has a sequence: the database gives "
            "its value. A form cannot change it.",
            field,
            hint="Remove the field from the form.",
        )
        return
    widget = field.widget or default_widget(target)
    if widget is None:
        shown = target.relation_kind or target.type
        yield _error(
            "missing-widget",
            f"The field '{target.entity}.{target.name}' ({shown}) has no default widget.",
            field,
            hint="Set 'widget: lines' with 'fields', or 'widget: custom'."
            if shown == "one_to_many"
            else "Set 'widget: custom' and write the widget by hand.",
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


def _check_lines_field(
    definition: AppDefinition,
    form: Form,
    operation: Operation | None,
    field: FormField,
    target: FieldTarget,
) -> Iterator[Diagnostic]:
    """A lines editor edits the records of a `one_to_many` relation that the operation writes.

    Each column is a field or a single relation of the related entity
    that a new line can take (ADR 0035).
    """
    if field.widget != "lines":
        if field.fields is not None:
            yield _error(
                "unsuitable-field", "'fields' is only for the widget 'lines'.", field, at="fields"
            )
        return
    relation = target.member
    if not isinstance(relation, Relation) or relation.kind != "one_to_many":
        return
    if field.fields is None:
        yield _error(
            "missing-key",
            "The widget 'lines' needs 'fields': the fields of the lines, one column each.",
            field,
        )
        return
    if operation is not None and target.name not in operation.lines:
        yield _error(
            "unsuitable-operation",
            f"The operation '{form.operation}' does not write the lines '{target.name}', so the "
            "form cannot send them.",
            field,
            at="widget",
            hint=f"Add '{target.name}' to 'lines' of the operation '{form.operation}'."
            if operation.kind in ("create", "update")
            else "Use a create or an update operation.",
        )
    if len(set(field.fields)) != len(field.fields):
        yield _error("duplicate-name", "The names in 'fields' must be unique.", field, at="fields")
    entity = definition.entities[relation.target]
    for name in dict.fromkeys(field.fields):
        column = yield from _resolve(definition, field, "fields", relation.target, name)
        if column is not None:
            yield from _check_lines_column(field, relation, name, column)
    columns = set(field.fields)
    for name, member in [*entity.fields.items(), *entity.relations.items()]:
        if isinstance(member, Field):
            needed = member.required and member.default is None and member.computed is None
        else:
            needed = member.required and member.kind in SINGLE_KINDS and name != relation.inverse
        if needed and name not in columns:
            yield _error(
                "invalid-value",
                f"The lines editor of '{target.name}' has no column for the required "
                f"{'field' if isinstance(member, Field) else 'relation'} "
                f"'{relation.target}.{name}', so a new line has no value for it.",
                field,
                at="fields",
                hint=f"Add '{name}' to 'fields'.",
            )


def _check_lines_column(
    field: FormField, relation: Relation, name: str, column: FieldTarget
) -> Iterator[Diagnostic]:
    """A column of a lines editor needs a default widget, and a value that the line stores."""
    member = column.member
    problem = None
    if member is None:
        problem = "is not a field or a relation of the lines"
    elif name == relation.inverse:
        problem = "is the relation to the record, which the form sets"
    elif isinstance(member, Field) and member.computed is not None:
        problem = "is computed"
    elif isinstance(member, Field) and member.translatable:
        problem = "is translatable, and a column edits one language only"
    elif column.relation_kind not in (None, *SINGLE_KINDS) or default_widget(column) is None:
        problem = f"({column.relation_kind or column.type}) has no widget in a lines editor"
    if problem is not None:
        yield _error(
            "unsuitable-field",
            f"The column '{name}' of the lines '{relation.target}' {problem}.",
            field,
            at="fields",
        )


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
    if isinstance(view, ApiViewBase):
        yield from _check_api_view(definition, view)
        return
    if view.entity not in definition.entities:
        yield _missing(view, "entity", "entity", view.entity, definition.entities)
        return
    entity = view.entity
    if view.states is not None:
        yield from _check_states(view.states, view.actions)
    if not isinstance(view, DetailView | CalendarView) and view.sort is not None:
        yield from _check_sort(definition, view.sort, entity, view.sort.field)
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
        case CalendarView():
            yield from _check_calendar(definition, entity, view)
        case DetailView():
            yield from _check_detail(definition, entity, view)


def _check_api_view(definition: AppDefinition, view: ApiView) -> Iterator[Diagnostic]:
    """The operation of a view of API data must exist, take the params, and answer with items."""
    api = definition.apis.get(view.api)
    if api is None:
        yield _missing(view, "source", "API", view.api, definition.apis)
        return
    if view.operation not in api.operations:
        matches = difflib.get_close_matches(view.operation, list(api.operations), n=1)
        yield _error(
            "unknown-reference",
            f"The API '{view.api}' has no operation '{view.operation}' in its 'operations'.",
            view,
            at="source",
            hint=f"Did you mean '{matches[0]}'?" if matches else None,
        )
        return
    if view.states is not None:
        yield from _check_states(view.states, {})
    data = api_data(definition, view)
    if data is None:
        # The document is not valid: `check_apis` reports it.
        return
    operation = data.operation
    if operation.body is not None:
        yield _error(
            "unsuitable-operation",
            f"The operation '{operation.id}' has a body, but a view sends no body.",
            view,
            at="source",
            hint="Use an operation without a body, or show its answer in a custom page.",
        )
    parameters = {p.name: p for p in operation.parameters}
    for name, value in view.params.items():
        if name not in parameters:
            matches = difflib.get_close_matches(name, list(parameters), n=1)
            yield _error(
                "unknown-reference",
                f"The operation '{operation.id}' has no parameter '{name}'.",
                view,
                at="params",
                hint=f"Did you mean '{matches[0]}'?" if matches else None,
            )
        elif isinstance(value, str) and value.startswith("$"):
            if not ROUTE_PARAM.match(value):
                yield _error(
                    "invalid-value",
                    f"The value '{value}' of the parameter '{name}' is not valid. A value that "
                    "starts with '$' must be '$route.<name>', a path parameter of the page.",
                    view,
                    at="params",
                )
        elif not accepts(parameters[name].schema, value, data.spec):
            yield _error(
                "invalid-value",
                f"The value {json.dumps(value)} of the parameter '{name}' does not match the "
                f"schema of the parameter in the document of the API '{view.api}'.",
                view,
                at="params",
            )
    for parameter in operation.parameters:
        if parameter.required and parameter.name not in view.params:
            yield _error(
                "missing-key",
                f"The operation '{operation.id}' needs the parameter '{parameter.name}'.",
                view,
                at="source",
                hint=f"Give its value in 'params', for example '{parameter.name}: ...', or "
                f"'$route.<name>' for a path parameter of the page.",
            )
    if data.item is None:
        yield _unsuitable_answer(view, operation.id)
        return
    what, verb = ("answer", "has") if isinstance(view, ApiDetailView) else ("items", "have")
    for element, key, paths in _api_view_paths(view):
        for path in paths:
            chain = property_chain(data.item, path, data.spec)
            if chain is None:
                names = [p.name for p in object_properties(data.item, data.spec) or ()]
                matches = difflib.get_close_matches(path, names, n=1)
                yield _error(
                    "unknown-reference",
                    f"The {what} of '{operation.id}' {verb} no property '{path}'.",
                    element,
                    at=key,
                    hint=f"Did you mean '{matches[0]}'?" if matches else None,
                )
            elif not query_value(chain[-1].schema, data.spec):
                yield _error(
                    "unsuitable-field",
                    f"The property '{path}' of the {what} of '{operation.id}' is an object. "
                    "A view shows a text, a number, a boolean, or a list of these.",
                    element,
                    at=key,
                    hint="Name a property of the object, for example 'address.city'.",
                )


def _unsuitable_answer(view: ApiView, operation: str) -> Diagnostic:
    if isinstance(view, ApiDetailView):
        need = "an answer that is an object"
    elif view.items is None:
        need = "an answer that is a list of objects"
    else:
        need = f"an answer with a list of objects in the property '{view.items}'"
    what = {"table": "A table", "cards": "A card list", "detail": "A detail view"}[view.kind]
    return _error(
        "unsuitable-operation",
        f"{what} needs {need}, but the operation '{operation}' does not give it.",
        view,
        at="items" if isinstance(view, ApiListViewBase) and view.items is not None else "source",
        hint="Set 'items' to the property with the list."
        if isinstance(view, ApiListViewBase) and view.items is None
        else None,
    )


def _api_view_paths(view: ApiView) -> Iterator[tuple[Element, str, list[str]]]:
    """Yield each element of a view of API data with a key and its property paths."""
    if isinstance(view, ApiListViewBase):
        if view.sort is not None:
            yield view.sort, "field", [view.sort.field]
        for filter_ in view.filters.values():
            yield filter_, "fields", filter_.fields
    match view:
        case ApiTableView():
            for name, column in view.columns.items():
                yield column, "field", [column.field or name]
        case ApiCardsView():
            card = view.card
            yield card, "title", [card.title]
            if card.subtitle is not None:
                yield card, "subtitle", [card.subtitle]
            yield card, "fields", card.fields
            yield card, "footer", card.footer
        case ApiDetailView():
            if view.header is not None:
                for key in ("title", "subtitle"):
                    path = getattr(view.header, key)
                    if path is not None:
                        yield view.header, key, [path]
            for section in view.sections.values():
                yield section, "fields", section.fields


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
        if tab.history and definition.entities[entity].history is None:
            yield _error(
                "invalid-option",
                f"The tab shows the change log, but the entity '{entity}' keeps none.",
                tab,
                at="history",
                hint=f"Add 'history: true' to the entity '{entity}'.",
            )
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
    elif isinstance(view, ApiViewBase):
        yield _error(
            "unsuitable-view",
            f"The view '{name}' shows API data. A list of records needs a view of an entity.",
            element,
            at=key,
        )
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
            yield from check_record_filter(definition, widget, widget.entity, widget.filter)
            if isinstance(widget, ChartWidget):
                yield from _check_chart_group(definition, widget)
        case ListWidget():
            views = definition.ui.views if definition.ui else {}
            yield from _check_list_view(views, widget, "view", widget.view, None)
            view = views.get(widget.view)
            if isinstance(view, TableView | CardsView) and view.entity in definition.entities:
                yield from check_record_filter(definition, widget, view.entity, widget.filter)
                if widget.sort is not None:
                    yield from _check_sort(definition, widget.sort, view.entity, widget.sort.field)
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
        if isinstance(target.member, Field) and target.member.currency_field is not None:
            yield from _check_one_currency(widget, widget.field, target.member.currency_field)


def _check_one_currency(
    widget: StatWidget | ChartWidget, field: str, currency_field: str
) -> Iterator[Diagnostic]:
    """An aggregate of amounts in the currencies of their records needs one currency a group."""
    path = currency_path(field, currency_field)
    if single_value(widget.filter, path) is not None:
        return
    if isinstance(widget, ChartWidget) and widget.group_by == path:
        return
    group = " or a group_by of it" if isinstance(widget, ChartWidget) else ""
    yield _error(
        "unsuitable-field",
        f"The field '{field}' has the currency of each record ('{currency_field}'). "
        f"The aggregate '{widget.aggregate}' adds amounts in more than one currency.",
        widget,
        at="field",
        hint=f"Add a filter on one currency, for example '{path}: EUR'{group}.",
    )


def _check_chart_group(definition: AppDefinition, widget: ChartWidget) -> Iterator[Diagnostic]:
    target = yield from _resolve(definition, widget, "group_by", widget.entity, widget.group_by)
    if target is None:
        return
    types = frozenset({"enum", *DATE_TYPES, *SINGLE_KINDS})
    yield from _check_suits(widget, "group_by", "A chart group", target, types)
    if "interval" in widget.model_fields_set and target.type not in DATE_TYPES:
        yield _error(
            "invalid-option",
            f"'interval' is only for a chart group of a date, but '{widget.group_by}' has the "
            f"type '{target.type}'.",
            widget,
            at="interval",
            hint="Remove the key 'interval', or group by a date or a date-time field.",
        )
    if widget.badge is not None and target.type == "enum":
        yield from _check_badge_ref(definition, widget, widget.badge, target)


def check_record_filter(
    definition: AppDefinition, element: Element, entity: str, record_filter: Mapping[str, object]
) -> Iterator[Diagnostic]:
    """The paths, the operators, and the values of the filter of a widget or of a job."""
    for path, condition in record_filter.items():
        target = yield from _resolve(definition, element, "filter", entity, path)
        if target is None:
            continue
        if target.type in FILE_TYPES:
            yield _no_file(element, "filter", "A filter", target)
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


def _check_calendar(
    definition: AppDefinition, entity: str, view: CalendarView
) -> Iterator[Diagnostic]:
    if view.label is not None:
        yield from _check_paths(definition, view, "label", entity, [view.label])
    types: list[str] = []
    for key in ("start", "end"):
        path = getattr(view, key)
        if path is None:
            continue
        target = yield from _resolve(definition, view, key, entity, path)
        if target is None:
            continue
        if target.type not in DATE_TYPES:
            yield _error(
                "unsuitable-field",
                f"The {key} of a calendar must be a date or a date-time field, but "
                f"'{path}' has the type '{target.type}'.",
                view,
                at=key,
            )
        else:
            types.append(target.type)
    if len(types) == 2 and types[0] != types[1]:
        yield _error(
            "unsuitable-field",
            "The start and the end of a calendar must have the same type.",
            view,
            at="end",
        )


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
    if card.image is not None:
        target = yield from _resolve(definition, card, "image", entity, card.image)
        if target is not None:
            yield from _check_suits(card, "image", "A card image", target, IMAGE_TYPES)


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


def _check_sort(
    definition: AppDefinition, element: Element, entity: str, path: str
) -> Iterator[Diagnostic]:
    target = yield from _resolve(definition, element, "field", entity, path)
    if target is not None and target.type in FILE_TYPES:
        yield _no_file(element, "field", "A sort", target)


def _no_file(element: Element, key: str, what: str, target: FieldTarget) -> Diagnostic:
    return _error(
        "unsuitable-field",
        f"{what} cannot use the field '{target.entity}.{target.name}' ({target.type}): it holds "
        "a file.",
        element,
        at=key,
        hint="Use another field.",
    )


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


TOKEN_GROUPS = {"width": "size", "max_width": "size", "padding": "spacing", "gap": "spacing"}
"""The token group that each style key needs. `color` keys need a color token."""
PAGE_KEYS = ("page", "link", "navigate")
"""The keys of UI elements that name a page (a route)."""


def check_ui_references(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Each token, page, layout, menu, view, form, and operation that the UI names must exist."""
    if definition.ui is None and not any(_has_ui_keys(page) for page in definition.pages.values()):
        return
    ui = definition.ui
    tokens = TokenTable.build(ui.tokens if ui else None)
    layouts = ui.layouts if ui else {}
    for element_id, element in definition.elements.items():
        if not element_id.startswith(("ui.", "pages.")) or element_id.startswith("ui.tokens"):
            continue
        yield from _check_token_refs(tokens, element)
        yield from _check_page_refs(definition, element)
        if isinstance(element, ActionBase) and element.placement is not None:
            yield from _check_placement(definition, element)
        match element:
            case Page():
                if element.layout is not None and element.layout not in layouts:
                    yield _missing(element, "layout", "layout", element.layout, layouts)
                if element.content is not None:
                    yield from _check_page_content(definition, element, element.content)
            case Defaults():
                if element.layout is not None and element.layout not in layouts:
                    yield _missing(element, "layout", "layout", element.layout, layouts)
            case Sidebar():
                menus = ui.navigation if ui else {}
                if element.navigation is not None and element.navigation not in menus:
                    yield _missing(element, "navigation", "menu", element.navigation, menus)
            case Layout() | Grid():
                for breakpoint in element.responsive:
                    yield from _check_breakpoint(tokens, element, "responsive", breakpoint)
            case Column():
                if element.hide_below is not None:
                    yield from _check_breakpoint(tokens, element, "hide_below", element.hide_below)
            case ViewResponsive():
                yield from _check_breakpoint(tokens, element, "below", element.below)
            case FormAction():
                forms = ui.forms if ui else {}
                if element.form not in forms:
                    yield _missing(element, "form", "form", element.form, forms)
            case OperationAction():
                operations = definition.operations
                operation = operations.get(element.operation)
                if operation is None:
                    yield _missing(element, "operation", "operation", element.operation, operations)
                elif operation.kind == "custom" and operation.params:
                    yield _error(
                        "unsuitable-operation",
                        f"The operation '{element.operation}' needs params, so an action "
                        "cannot run it without a form.",
                        element,
                        at="operation",
                        hint="Use a form action with a form for the operation: "
                        f"{{ kind: form, form: <a form of '{element.operation}'> }}.",
                    )
            case NavigateAction():
                page = definition.pages.get(element.page)
                params = _path_params(page.path) if page else set[str]()
                for param in element.params:
                    if page is not None and param not in params:
                        yield _missing(element, "params", "path parameter", param, params)
            case BoardView():
                yield from _check_board_move(definition, element)
            case _:
                pass


def _check_placement(definition: AppDefinition, action: ActionBase) -> Iterator[Diagnostic]:
    parts = action.id.split(".")
    if len(parts) != 4 or parts[0] != "pages" or parts[2] != "actions":
        yield _error(
            "invalid-option",
            "Only a page action has 'placement'.",
            action,
            at="placement",
            hint="Remove 'placement', or move the action to 'pages.<page>.actions'.",
        )
        return
    if action.placement == "page":
        return
    ui = definition.ui
    page = definition.pages[parts[1]]
    layout_name = page.layout or (ui.defaults.layout if ui and ui.defaults else None)
    layout = ui.layouts.get(layout_name) if ui and layout_name else None
    if layout is not None and layout.topbar is None:
        yield _error(
            "invalid-option",
            f"The action has the placement '{action.placement}', but the layout "
            f"'{layout_name}' of the page '{parts[1]}' has no top bar.",
            action,
            at="placement",
            hint="Use 'placement: page', or give the layout a top bar.",
        )
    elif layout is None and layout_name is None:
        yield _error(
            "invalid-option",
            f"The action has the placement '{action.placement}', but the page "
            f"'{parts[1]}' has no layout, so it has no top bar.",
            action,
            at="placement",
            hint="Use 'placement: page', or give the page a layout with a top bar.",
        )


def _has_ui_keys(page: Page) -> bool:
    return page.layout is not None or page.content is not None or bool(page.actions)


def _path_params(path: str) -> set[str]:
    return set(re.findall(r"\{([a-z][a-z0-9_]*)\}", path))


def _check_token_refs(tokens: TokenTable, element: Element) -> Iterator[Diagnostic]:
    for key in type(element).model_fields:
        value = getattr(element, key)
        if not isinstance(value, str) or not value.startswith("{"):
            continue
        group = "color" if key == "color" else TOKEN_GROUPS.get(key)
        if group is None:
            continue
        path = tokens.reference_target(value)
        entry = tokens.tokens.get(path or "")
        if entry is None:
            yield _missing(element, key, "token", path or value, tokens.tokens)
        elif entry.group != group:
            yield _error(
                "unsuitable-token",
                f"The key '{key}' needs a token in '{group}', but '{path}' is in '{entry.group}'.",
                element,
                at=key,
            )


def _check_breakpoint(
    tokens: TokenTable, element: Element, key: str, name: str
) -> Iterator[Diagnostic]:
    path = f"breakpoint.{name}"
    if path not in tokens.tokens:
        breakpoints = [
            p.removeprefix("breakpoint.") for p in tokens.tokens if p.startswith("breakpoint.")
        ]
        yield _missing(element, key, "breakpoint token", name, breakpoints)


def _check_page_refs(definition: AppDefinition, element: Element) -> Iterator[Diagnostic]:
    for key in PAGE_KEYS:
        if key not in type(element).model_fields:
            continue
        name = getattr(element, key)
        if isinstance(name, str) and name not in definition.pages:
            yield _missing(element, key, "page", name, definition.pages)


def _check_page_content(
    definition: AppDefinition, page: Page, content: PageContent
) -> Iterator[Diagnostic]:
    ui = definition.ui
    if content.view is not None:
        views = ui.views if ui else {}
        view = views.get(content.view)
        if view is None:
            yield _missing(content, "view", "view", content.view, views)
        elif isinstance(view, ApiViewBase):
            yield from _check_api_page(page, content, view)
        elif isinstance(view, DetailView) and not _path_params(page.path):
            yield _error(
                "unsuitable-view",
                f"The detail view '{content.view}' shows one record, so the page path needs "
                "a path parameter.",
                content,
                at="view",
                hint="Use a path such as /tasks/{id}.",
            )
        elif page.entity is not None and view.entity != page.entity:
            yield _error(
                "unsuitable-view",
                f"The view '{content.view}' shows '{view.entity}', but the page shows "
                f"'{page.entity}'.",
                content,
                at="view",
            )
    if content.form is not None:
        forms = ui.forms if ui else {}
        if content.form not in forms:
            yield _missing(content, "form", "form", content.form, forms)
    if content.dashboard is not None:
        dashboards = ui.dashboards if ui else {}
        if content.dashboard not in dashboards:
            yield _missing(content, "dashboard", "dashboard", content.dashboard, dashboards)


def _check_api_page(page: Page, content: PageContent, view: ApiView) -> Iterator[Diagnostic]:
    """A page with a view of API data has no entity, and has each path parameter of the view."""
    if page.entity is not None:
        yield _error(
            "unsuitable-view",
            f"The view '{content.view}' shows API data, but the page shows '{page.entity}'.",
            content,
            at="view",
            hint="Remove 'entity' from the page.",
        )
    params = _path_params(page.path)
    for name, value in view.params.items():
        match = ROUTE_PARAM.match(value) if isinstance(value, str) else None
        if match is not None and match[1] not in params:
            yield _error(
                "unsuitable-view",
                f"The view '{content.view}' gives the parameter '{name}' the path parameter "
                f"'{match[1]}' ('{value}'), but the path '{page.path}' does not have it.",
                content,
                at="view",
                hint=f"Add '{{{match[1]}}}' to the path of the page.",
            )


def _check_board_move(definition: AppDefinition, view: BoardView) -> Iterator[Diagnostic]:
    if view.move is None:
        return
    operation = definition.operations.get(view.move)
    if operation is None:
        yield _missing(view, "move", "operation", view.move, definition.operations)
        return
    suits = operation.entity == view.entity and (
        operation.kind == "update"
        or (operation.kind == "custom" and view.group_by in operation.params)
    )
    if not suits:
        yield _error(
            "unsuitable-operation",
            f"A board move needs an update operation on '{view.entity}', or a custom "
            f"operation with the parameter '{view.group_by}'. '{view.move}' is a "
            f"{operation.kind} operation on '{operation.entity}'.",
            view,
            at="move",
        )
