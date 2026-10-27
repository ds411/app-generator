"""The forms of the front-end apps: create, edit, and custom operation forms (ADR 0003).

The shared UI templates in `templates/ui/forms/` render the `FormPlan` of
each form. A form keeps the values of its widgets in a `Values` object:
text as a string (empty: `""`), numbers, dates, enum values, and single
relations as a value or `null`, many-to-many relations as a list of IDs,
and booleans. On submit, the form turns the values into the input of its
operation, checks the input with the zod schema of the entity slice and
with the rules of the form, and calls the operation.

A file field (ADR 0027) keeps the file of the record (`FileValue`), a
new `File`, or `null`. The input of the operation has no files: after
the operation, the form uploads the new files and deletes the removed
files with the file API of the entity (`<entity>Files`).

A point field (ADR 0046) keeps a `GeoPoint` or `null`. Its widget has
an input for the latitude and one for the longitude: a value that is
not a number is `NaN`, so that the zod schema of the entity reports it.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from appgen.bindings.shared.auth import record_rules
from appgen.bindings.shared.gaps import form_values, gap_spec
from appgen.bindings.shared.i18n import LanguagePlan, i18n_plan, text_js
from appgen.bindings.shared.lines import LineItem, line_item, lines_operations
from appgen.bindings.shared.totals import TsTotal, entity_totals
from appgen.bindings.shared.typescript import Member, members, translations_key
from appgen.bindings.shared.ui import css_class_var, js
from appgen.bindings.shared.views import ViewContext, definition_display, label
from appgen.dsl.auth import ME
from appgen.dsl.expressions import expression_paths, expression_totals, parse_expression
from appgen.dsl.model import AppDefinition, Field, Operation
from appgen.dsl.storage import format_size
from appgen.dsl.ui.common import Grid
from appgen.dsl.ui.fields import FieldTarget, default_widget, resolve_path
from appgen.dsl.ui.forms import CompareRule, CustomRule, Form, FormField
from appgen.gen.binding import Output
from appgen.gen.naming import camel, kebab, pascal, snake

type ValueKind = Literal[
    "text",
    "number",
    "enum",
    "one",
    "many",
    "boolean",
    "date",
    "datetime",
    "json",
    "file",
    "lines",
    "point",
]

_KINDS: dict[str, ValueKind] = {
    "string": "text",
    "text": "text",
    "email": "text",
    "url": "text",
    "uuid": "text",
    "integer": "number",
    "decimal": "number",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "enum": "enum",
    "json": "json",
    "point": "point",
}
_EMPTY: dict[ValueKind, str] = {
    "text": '""',
    "many": "[]",
    "boolean": "false",
}
_INPUT_TYPES = {"email": "email", "url": "url"}
NUMBER_FORMATS = frozenset({"number", "currency", "percent"})
"""The field formats that a number widget shows next to its value."""


@dataclass(frozen=True, slots=True)
class Check:
    """A rule of a form field: a TypeScript condition that is true for a value that breaks it."""

    condition: str
    message: str
    element_id: str


@dataclass(slots=True)
class FieldPlan:
    """A field of a form, with its widget and its rules."""

    name: str
    key: str
    """The key in the values and in the input, for example `dueDate` or `ownerId`."""
    element_id: str
    widget: str
    label: str
    kind: ValueKind
    value_type: str
    """The TypeScript type of the value in the form."""
    empty: str
    """The TypeScript value of an empty widget."""
    placeholder: str | None = None
    help: str | None = None
    span: int = 1
    rows: int | None = None
    step: float | None = None
    format: str | None = None
    """For a number: the display format of the field (`number`, `currency`, or `percent`)."""
    currency: str | None = None
    """For a `currency` number: the ISO 4217 code, or None for the default currency."""
    currency_expr: str | None = None
    """For a `currency` number: the TypeScript code of the currency of the record
    (`currency_field`), or None."""
    input_type: str = "text"
    required: bool = False
    required_message: str = "Enter a value."
    required_id: str | None = None
    """The element ID of the `required` rule, if the form sets it."""
    to_input: str = ""
    """A TypeScript expression of the input value, of `values`."""
    options: str | None = None
    """For an enum: the options `{ value, label }[]`. For a relation: of `lookups`."""
    target: str | None = None
    """The target entity of a relation."""
    source: str | None = None
    """For a relation of a form that searches on the server: the option source, for example
    `personOptions`. The field then has no `options`."""
    mentions: str | None = None
    """For a text with mentions (ADR 0043): the user entity. `options` or `source` give the
    users that the widget suggests after `@`."""
    initial: str = ""
    """The TypeScript initial value, of `record` and `routeParams`."""
    checks: list[Check] = field(default_factory=list[Check])
    rules_id: str | None = None
    gap_module: str | None = None
    gap_name: str | None = None
    classes: str = ""
    """The grid classes of the field: its span, with the responsive overrides."""
    owner: bool = False
    """True for the owner of an owner rule (ADR 0018): a user of the rule does not see it."""
    fixed: bool = False
    """True if a condition of a record rule with one value can set the field (ADR 0025).

    A user of the rule does not see the field, and the form sets the value.
    """
    languages: list[LanguagePlan] = field(default_factory=list[LanguagePlan])
    """For a translatable field (ADR 0026): the other languages.

    The widget of the field edits the value of the default language, and
    one more widget edits the value of each other language.
    """
    translations_key: str = ""
    """For a translatable field: the key of its values in each language, `titleTranslations`."""
    translations_initial: str = ""
    """For a translatable field: the TypeScript initial values of the other languages."""
    translations_input: str = ""
    """For a translatable field: the TypeScript input of the values of all languages."""
    file_rule: str | None = None
    """For a file field: the TypeScript rule of the files, `{ maxSize, types }`."""
    lines: LinesPlan | None = None
    """For a lines editor (ADR 0035): its rows and columns."""
    prefix: str = ""
    """For a column of a lines editor: the start of the names of its constants, `lines_`."""

    @property
    def options_const(self) -> str:
        """Return the constant with the options of an enum field, for example `STATUS_OPTIONS`."""
        return f"{self.prefix}{snake(self.key)}_options".upper()


@dataclass(slots=True)
class LinesPlan:
    """A lines editor (ADR 0035): a row for each record of a `one_to_many` relation.

    The values of the form keep the rows. A row has a key for React, the
    ID of a line of the record, the line of the record, and the value of
    each column. The input of the operation gets the items of the rows.
    """

    item: LineItem
    columns: list[FieldPlan]
    """The fields of a line, one column each. Their `to_input` reads the row `line`."""

    @property
    def row_type(self) -> str:
        """Return the TypeScript type of a row, for example `LinesRow`."""
        return f"{pascal(self.item.relation)}Row"

    @property
    def record_type(self) -> str:
        """Return the TypeScript type of a line of the record, for example `InvoiceLine`."""
        return pascal(self.item.target)


@dataclass(frozen=True, slots=True)
class LinesTotalPlan:
    """A total of the lines of the form, a key of the record of the preview (ADR 0034)."""

    key: str
    """The key in the record, for example `sumLinesAmount`."""
    code: str
    """The TypeScript value of the total, of `values`."""


@dataclass(frozen=True, slots=True)
class PreviewPlan:
    """A computed field with a total of the lines, which the form shows before the save."""

    element_id: str
    label: str
    text: str
    """The TypeScript text of the value, of the record `preview`."""
    lines: list[str]
    """The keys of the lines editors with the lines of its totals."""

    @property
    def editor(self) -> str:
        """Return the key of the lines editor that shows the field: the first of `lines`."""
        return self.lines[0]


@dataclass(frozen=True, slots=True)
class SectionPlan:
    name: str
    element_id: str
    title: str | None
    description: str | None
    fields: list[FieldPlan]


@dataclass(frozen=True, slots=True)
class FormRulePlan:
    """A rule of the form: a compare rule, or a custom rule with its gap function."""

    element_id: str
    fields: list[str]
    """The keys of the fields that show the message."""
    message: str
    condition: str | None = None
    """For a compare rule: a TypeScript condition of `values` that is true if the rule breaks."""
    gap_module: str | None = None
    gap_name: str | None = None


@dataclass(slots=True)
class FormPlan:
    """The values of a form that its template needs."""

    name: str
    form: Form
    entity: str
    kind: str
    """The kind of the operation: `create`, `update`, or `custom`."""
    operation: str
    fields: list[FieldPlan]
    sections: list[SectionPlan]
    loose: list[FieldPlan]
    """The fields that no section has, in source order."""
    rules: list[FormRulePlan]
    grid: str
    schema: str
    """The TypeScript zod schema of the input."""
    input_type: str
    """The TypeScript type of the input of the operation."""
    call: str
    """The TypeScript call of the operation, of `input` and `record`."""
    imports: list[str]
    """The import lines of the entity slices, the operations, and the gaps."""
    lookups: list[str]
    """The target entities of the relation fields that the form loads, sorted by name. A form
    that searches on the server loads none."""
    host_page: str | None = None
    """The page that shows the form as its content, or None."""
    record_param: str | None = None
    """The path parameter of the host page with the ID of the record."""
    navigate: str | None = None
    """The TypeScript path to open after a success, of `result`, or None."""
    rule_values: str = ""
    """The TypeScript type of the values that the custom rules check."""
    route_params: bool = False
    """True if a default reads a path parameter of the page."""
    me: bool = False
    """True if a default is `$me`: the first values read `me`, the ID of the signed-in user."""
    widgets: set[str] = field(default_factory=set[str])
    """The widgets that the form uses."""
    lines_type: str | None = None
    """For an operation with lines (ADR 0035): the TypeScript type of its lines."""
    totals: list[LinesTotalPlan] = field(default_factory=list[LinesTotalPlan])
    """The totals of the lines of the form, for the preview."""
    previews: list[PreviewPlan] = field(default_factory=list[PreviewPlan])
    """The computed fields with totals of the lines that the form shows before the save."""

    @property
    def lines(self) -> list[FieldPlan]:
        """Return the lines editors of the form (ADR 0035)."""
        return [f for f in self.fields if f.lines is not None]

    @property
    def widget_fields(self) -> list[FieldPlan]:
        """Return the fields with a widget: the fields of the form and the columns of the lines."""
        return [
            column
            for f in self.fields
            for column in (f.lines.columns if f.lines is not None else [f])
        ]

    @property
    def loads_lines(self) -> bool:
        """Return True if the form edits a record with lines: it reads the lines first."""
        return self.kind == "update" and bool(self.lines)

    @property
    def files(self) -> list[FieldPlan]:
        """Return the file fields of the form, which upload their files after the operation."""
        return [f for f in self.fields if f.kind == "file"]

    @property
    def file_imports(self) -> list[str]:
        """Return the names that the form imports from the module of the file widget."""
        names = ["FileInput"] if any(f.widget != "custom" for f in self.files) else []
        if any("fileAllowed(" in check.condition for f in self.files for check in f.checks):
            names.append("fileAllowed")
        return names

    @property
    def owner(self) -> FieldPlan | None:
        """Return the field of the owner of an owner rule of the entity (ADR 0018), or None."""
        return next((f for f in self.fields if f.owner), None)

    @property
    def fixed(self) -> list[FieldPlan]:
        """Return the fields that a condition of a record rule can set (ADR 0025)."""
        return [f for f in self.fields if f.fixed]

    @property
    def scoped(self) -> bool:
        """Return True if a record rule can hide fields of the form (ADR 0018, ADR 0025)."""
        return any(f.owner or f.fixed for f in self.fields)

    @property
    def type(self) -> str:
        return pascal(self.entity)

    @property
    def component(self) -> str:
        return f"{pascal(self.name)}Form"

    @property
    def needs_record(self) -> bool:
        """True if the form edits a record or runs a custom operation on it."""
        return self.kind != "create"

    @property
    def mode(self) -> str:
        """The form mode. A `page` form without a page shows in a dialog."""
        mode = self.form.mode
        return "dialog" if mode == "page" and self.host_page is None else mode

    @property
    def page_href(self) -> str | None:
        """For a form in `page` mode: the TypeScript path of its page, of `record`."""
        if self.mode != "page" or self.host_page is None:
            return None
        if self.record_param is None:
            return f"pageHref({js(camel(self.host_page))})"
        return f"pageHref({js(camel(self.host_page))}, {{ {self.record_param}: record.id }})"

    @property
    def module(self) -> str:
        return f"@/features/{kebab(self.name)}-form"


@dataclass(slots=True)
class SignUpPlan:
    """The sign-up form of the front ends (ADR 0016): fields of the user entity, and a password."""

    element_id: str
    entity: str
    fields: list[FieldPlan]
    schema: str
    """The TypeScript zod schema of the fields, without the password."""
    role: str | None
    """The role of a new user, or None without `access`."""
    widgets: set[str]


class FormContext:
    """The form plans of a definition, for the form templates and the actions."""

    def __init__(self, definition: AppDefinition, *, server: bool = False) -> None:
        """Make the context. With `server`, the relation fields search their options on the API."""
        self.definition = definition
        self.server = server
        ui = definition.ui
        self.names: list[str] = list(ui.forms) if ui else []
        self._plans: dict[str, FormPlan] = {}
        self.sign_up = sign_up_plan(definition)

    def plan(self, name: str) -> FormPlan:
        """Return the plan of a form."""
        if name not in self._plans:
            self._plans[name] = _build(self.definition, name, self.server)
        return self._plans[name]

    @property
    def used(self) -> bool:
        """Return True if the app has a form: a form of the UI, or the sign-up form."""
        return bool(self.names) or self.sign_up is not None

    @property
    def widgets(self) -> set[str]:
        """Return the widgets of all forms, for the runtime files and the components."""
        widgets = {w for name in self.names for w in self.plan(name).widgets}
        return widgets | (self.sign_up.widgets if self.sign_up else set())

    @property
    def relations(self) -> bool:
        """Return True if a form has a relation field."""
        return any(f.target for name in self.names for f in self.plan(name).widget_fields)

    @property
    def files(self) -> bool:
        """Return True if a form has a file field."""
        return any(self.plan(name).files for name in self.names)

    @property
    def lines(self) -> bool:
        """Return True if a form has a lines editor (ADR 0035)."""
        return any(self.plan(name).lines for name in self.names)

    @property
    def previews(self) -> bool:
        """Return True if a form shows totals of its lines before the save (ADR 0034)."""
        return any(self.plan(name).totals for name in self.names)


def _build(definition: AppDefinition, name: str, server: bool = False) -> FormPlan:
    assert definition.ui is not None
    form = definition.ui.forms[name]
    entity = form.entity
    operation: Operation = definition.operations[form.operation]
    params = operation.params if operation.kind == "custom" else None
    by_name = {m.name: m for m in members(entity, definition.entities[entity])}
    rules = record_rules(definition).get(entity) if operation.kind in ("create", "update") else None
    owner = rules.path[0].relation if rules is not None and rules.direct else None
    fields: list[FieldPlan] = []
    route_params = False
    for field_name, form_field in form.fields.items():
        default = form.defaults.get(field_name)
        if isinstance(default, str) and default.startswith("$route."):
            route_params = True
        if params is None and form_field.widget == "lines":
            plan = _lines_field(definition, entity, field_name, form_field, operation, server)
        elif params is not None and field_name in params:
            plan = _param_field(field_name, form_field, params[field_name])
        else:
            plan = _member_field(definition, entity, field_name, form_field, by_name[field_name])
        if plan.lines is None:
            plan.initial = _initial(
                plan, default, operation.kind == "update", by_name.get(field_name)
            )
        _rules(plan, form_field)
        if plan.widget == "custom":
            spec = gap_spec(definition, form_field.id, "form_field")
            plan.gap_module = spec.module + ".gen"
            plan.gap_name = spec.name
        plan.classes = _span_classes(form_field.span, form.grid)
        plan.owner = field_name == owner
        plan.fixed = rules is not None and field_name in rules.fixed
        if server and plan.target is not None and plan.widget != "custom":
            # The server searches the options: a select or a radio of a relation is a search box.
            plan.source = f"{camel(plan.target)}Options"
            plan.options = None
            plan.widget = "relation"
        if server and plan.mentions is not None:
            # The server searches the users of the mentions.
            plan.source = f"{camel(plan.mentions)}Options"
            plan.options = None
        member = by_name.get(field_name)
        if params is None and member is not None and member.field and member.field.translatable:
            _translations(definition, plan, operation.kind == "update")
        fields.append(plan)
    by_field = {f.name: f for f in fields}
    sections = [
        SectionPlan(
            s_name,
            section.id,
            section.title,
            section.description,
            [by_field[f] for f in section.fields],
        )
        for s_name, section in form.sections.items()
    ]
    placed = {f for section in form.sections.values() for f in section.fields}
    loose = [f for f in fields if f.name not in placed]
    rules = [_form_rule(definition, rule, by_field) for rule in form.rules.values()]
    kebab_entity = kebab(entity)
    type_name = pascal(entity)
    imports: list[str] = []
    if operation.kind == "custom":
        params_type = f"{pascal(form.operation)}Params"
        schema = f"{camel(form.operation)}ParamsSchema"
        input_type = params_type
        entity_names = [schema, f"type {params_type}", f"type {type_name}"]
        call = f"{camel(form.operation)}(record.id, input as {params_type})"
        imports.append(
            f'import {{ {camel(form.operation)} }} from "@/features/{kebab(form.operation)}";'
        )
    else:
        base = "Input" if operation.kind == "create" else "Patch"
        schema = f"{camel(entity)}{base}Schema"
        input_type = (
            f"{type_name}Input" if operation.kind == "create" else f"Partial<{type_name}Input>"
        )
        op = camel(form.operation)
        entity_names = [op, schema, f"type {type_name}"]
        if operation.kind == "create":
            entity_names.append(f"type {type_name}Input")
        if any(f.kind == "file" for f in fields):
            entity_names.insert(1, f"{camel(entity)}Files")
        call = (
            f"{op}(input as {type_name}Input)"
            if operation.kind == "create"
            else f"{op}(record.id, input)"
        )
    lines_fields = {f.name: f for f in fields if f.lines is not None}
    previews = _previews(definition, entity, lines_fields)
    totals = [
        LinesTotalPlan(total.key, _lines_total(total, lines_fields[total.relation]))
        for total in entity_totals(definition, entity)
        if previews and total.relation in lines_fields
    ]
    preview_keys = {key for preview in previews for key in preview.lines}
    lines_type = None
    if operation.lines and operation.kind in ("create", "update"):
        # The function of an operation with lines is in its feature slice (ADR 0035).
        lines_type = lines_operations(definition)[form.operation].type
        entity_names.remove(camel(form.operation))
        names = [camel(form.operation)]
        if lines_fields:
            names.append(f"type {lines_type}")
            call = call.removesuffix(")") + ", lines)"
        imports.append(
            f'import {{ {", ".join(names)} }} from "@/features/{kebab(form.operation)}";'
        )
    widget_fields = [c for f in fields for c in (f.lines.columns if f.lines else [f])]
    sources = sorted({t for f in widget_fields if f.source for t in (f.target or f.mentions,) if t})
    line_names = _line_imports(fields, operation.kind == "update", preview_keys)
    if entity in sources:
        entity_names.append(f"{camel(entity)}Options")
    entity_names += line_names.pop(entity, [])
    if previews:
        entity_names.append(f"{camel(entity)}Defaults")
    imports.insert(0, f'import {{ {", ".join(entity_names)} }} from "@/entities/{kebab_entity}";')
    targets = sorted({t for t in sources if t != entity} | set(line_names))
    imports[1:1] = [
        f"import {{ {', '.join(_target_names(t, sources, line_names))} }} "
        f'from "@/entities/{kebab(t)}";'
        for t in targets
    ]
    for rule in rules:
        if rule.gap_name:
            imports.append(f'import {{ {rule.gap_name} }} from "{rule.gap_module}";')
    for f in fields:
        if f.gap_name:
            imports.append(f'import {{ {f.gap_name} }} from "{f.gap_module}";')
    lookups = sorted(
        {t for f in widget_fields if not f.source for t in (f.target or f.mentions,) if t}
    )
    host = next(
        (
            p_name
            for p_name, page in definition.pages.items()
            if page.content is not None and page.content.form == name
        ),
        None,
    )
    if params is None:
        _currency_exprs(definition, entity, fields, lookups, operation.kind != "create")
    return FormPlan(
        name=name,
        form=form,
        entity=entity,
        kind=operation.kind,
        operation=form.operation,
        fields=fields,
        sections=sections,
        loose=loose,
        rules=rules,
        grid=_grid(form.grid),
        schema=_schema(schema, _input_keys(fields)),
        input_type=input_type,
        call=call,
        imports=imports,
        lookups=lookups,
        host_page=host,
        record_param=_record_param(definition, host) if host else None,
        navigate=_navigate(definition, form, entity, operation),
        rule_values=form_values(definition, name)[0],
        route_params=route_params,
        me=any(form.defaults.get(f) == ME for f in form.fields),
        widgets={f.widget for f in [*fields, *widget_fields]}
        | ({"number_format"} if any(f.format for f in widget_fields) else set()),
        lines_type=lines_type,
        totals=totals,
        previews=previews,
    )


def _currency_exprs(
    definition: AppDefinition,
    entity: str,
    fields: list[FieldPlan],
    lookups: list[str],
    record: bool,
) -> None:
    """Give each amount of a form the currency of its record (`currency_field`).

    The currency is the value of a field of the form, else the value of the
    record that the form edits. Through one relation, it is a field of the
    record that the relation field selects. Else the amount has the
    currency of the field.
    """
    by_name = {f.name: f for f in fields}
    entity_fields = definition.entities[entity].fields
    for plan in fields:
        value = entity_fields.get(plan.name)
        if plan.format != "currency" or value is None or value.currency_field is None:
            continue
        head, _, tail = value.currency_field.partition(".")
        source = by_name.get(head)
        code = None
        if not tail and source is not None:
            code = f"values.{source.key}"
        elif not tail and record:
            code = f"record?.{camel(head)}"
        elif tail and "." not in tail and source is not None and source.target in lookups:
            related = f"related.{camel(source.target)}"
            code = f'{related}.get(values.{source.key} ?? "")?.{camel(tail)}'
        if code is not None:
            plan.currency_expr = f"{code} ?? {js(plan.currency)}" if plan.currency else code


def _line_imports(
    fields: list[FieldPlan], update: bool, preview_keys: set[str]
) -> dict[str, list[str]]:
    """Return the names that the lines editors import from the slice of each entity of lines."""
    names: dict[str, list[str]] = {}
    for f in fields:
        if f.lines is None:
            continue
        item = f.lines.item
        found = names.setdefault(item.target, [])
        found.append(item.schema)
        if f.key in preview_keys:
            found.append(f"{camel(item.target)}Defaults")
        if update:
            found += [f"type {f.lines.record_type}", item.list_function]
    return {target: list(dict.fromkeys(found)) for target, found in names.items()}


def _target_names(target: str, sources: list[str], line_names: dict[str, list[str]]) -> list[str]:
    """Return the names that a form imports from the slice of another entity."""
    names = [f"{camel(target)}Options"] if target in sources else []
    return names + line_names.get(target, [])


def _lines_field(
    definition: AppDefinition,
    entity: str,
    name: str,
    form_field: FormField,
    operation: Operation,
    server: bool,
) -> FieldPlan:
    """Return the plan of a lines editor (ADR 0035): a column for each field of the lines."""
    item = line_item(definition, entity, name)
    relation = definition.entities[entity].relations[name]
    by_name = {m.name: m for m in members(item.target, definition.entities[item.target])}
    columns: list[FieldPlan] = []
    for column_name in form_field.fields or []:
        member = by_name[column_name]
        column = _member_field(definition, item.target, column_name, FormField(), member)
        column.element_id = member.element_id
        column.prefix = f"{snake(name)}_"
        column.initial = _initial(column, None, False, member)
        column.to_input = column.to_input.replace("values.", "line.")
        if server and column.target is not None:
            column.source = f"{camel(column.target)}Options"
            column.options = None
            column.widget = "relation"
        columns.append(column)
    plan = FieldPlan(
        name=name,
        key=item.key,
        element_id=form_field.id,
        widget="lines",
        label=form_field.label or relation.label or label(name),
        kind="lines",
        value_type=f"{pascal(name)}Row[]",
        empty="[]",
        required_message="Add a line.",
        lines=LinesPlan(item, columns),
    )
    update = operation.kind == "update"
    plan.initial = f"lines?.{item.key}.map({item.key}Row) ?? []" if update else "[]"
    _widget_options(plan, form_field)
    return plan


def _lines_total(total: TsTotal, lines: FieldPlan) -> str:
    """Return the TypeScript value of a total of the rows of a lines editor (ADR 0034)."""
    conditions = ", ".join(f"[{js(k)}, {js(op)}, {js(v)}]" for k, op, v in total.conditions())
    number = js(camel(total.number)) if total.number else "null"
    rows = f"{lines.key}Records(values.{lines.key})"
    extra = f", [{conditions}]" if conditions else ""
    return f"linesTotal({js(total.function)}, {rows}, {number}{extra})"


def _previews(
    definition: AppDefinition, entity: str, lines: dict[str, FieldPlan]
) -> list[PreviewPlan]:
    """Return the computed fields with totals of the lines editors, for the preview.

    A field that reads a related record (a path with a `.`) is not in the
    preview: the form has no related records.
    """
    views = ViewContext(definition)
    found: list[PreviewPlan] = []
    for name, member in definition.entities[entity].fields.items():
        if member.computed is None:
            continue
        expression = parse_expression(member.computed)
        relations = [t.relation for t in expression_totals(expression) if t.relation in lines]
        if not relations or any("." in path for path in expression_paths(expression)):
            continue
        value = views.value(entity, name, row="preview")
        keys = list(dict.fromkeys(lines[relation].key for relation in relations))
        found.append(PreviewPlan(member.id, member.label or label(name), value.text_expr, keys))
    return found


def sign_up_plan(definition: AppDefinition) -> SignUpPlan | None:
    """Return the plan of the sign-up form, or None without `auth.sign_up`."""
    auth = definition.auth
    if auth is None or auth.sign_up is None:
        return None
    entity = auth.user_entity
    element = definition.entities[entity]
    by_name = {m.name: m for m in members(entity, element)}
    fields: list[FieldPlan] = []
    for name in auth.sign_up.fields:
        member = by_name[name]
        plan = _member_field(definition, entity, name, FormField(), member)
        plan.element_id = element.fields[name].id
        plan.initial = _initial(plan, None, False, member)
        fields.append(plan)
    keys = ", ".join(f"{f.key}: true" for f in fields)
    role = None
    if definition.access is not None:
        role_field = element.fields[definition.access.role_field]
        role = auth.sign_up.default_role or str(role_field.default)
    return SignUpPlan(
        element_id=auth.sign_up.id,
        entity=entity,
        fields=fields,
        schema=f"{camel(entity)}InputSchema.pick({{ {keys} }})",
        role=role,
        widgets={f.widget for f in fields}
        | ({"number_format"} if any(f.format for f in fields) else set()),
    )


def _member_field(
    definition: AppDefinition, entity: str, name: str, form_field: FormField, member: Member
) -> FieldPlan:
    target = resolve_path(definition, entity, name)
    widget = form_field.widget or default_widget(target) or "custom"
    relation = member.relation
    if relation is not None:
        many = relation.kind == "many_to_many"
        kind: ValueKind = "many" if many else "one"
        target_entity = relation.target
        display = camel(definition_display(definition.entities[target_entity]))
        plan = FieldPlan(
            name=name,
            key=member.key,
            element_id=form_field.id,
            widget=widget,
            label=form_field.label or relation.label or label(name),
            kind=kind,
            value_type="string[]" if many else "string | null",
            empty="[]" if many else "null",
            target=target_entity,
            options=(
                f"[...lookups.{camel(target_entity)}.values()].map((item) => "
                f'({{ value: item.id, label: String(item.{display} ?? "") }}))'
            ),
            required=member.input_required,
            required_message="Select a value.",
        )
    else:
        assert member.field is not None
        plan = _value_field(name, member.key, form_field, member.field, widget)
        plan.required = member.input_required
        if member.field.mentions and definition.auth is not None and widget != "custom":
            # The widget suggests the users after `@` (ADR 0043).
            users = definition.auth.user_entity
            display = camel(definition_display(definition.entities[users]))
            plan.widget = "mentions"
            plan.mentions = users
            plan.options = (
                f"[...lookups.{camel(users)}.values()].map((item) => "
                f'({{ value: item.id, label: String(item.{display} ?? "") }}))'
            )
    plan.to_input = _to_input(plan, member.nullable, member.input_required)
    _widget_options(plan, form_field)
    return plan


def _param_field(name: str, form_field: FormField, param: Field) -> FieldPlan:
    widget = form_field.widget or default_widget_of(param) or "custom"
    plan = _value_field(name, camel(name), form_field, param, widget)
    plan.required = param.required
    plan.to_input = _to_input(plan, not param.required, param.required)
    _widget_options(plan, form_field)
    return plan


def default_widget_of(param: Field) -> str | None:
    """Return the default widget of an operation parameter."""
    return default_widget(FieldTarget("", "", param))


def _value_field(
    name: str, key: str, form_field: FormField, value: Field, widget: str
) -> FieldPlan:
    if value.is_file:
        return _file_field(name, key, form_field, value, widget)
    kind = _KINDS[value.type]
    if kind == "text":
        value_type = "string"
    elif kind == "json":
        value_type = "unknown"
    elif kind == "boolean":
        value_type = "boolean"
    elif kind == "number":
        value_type = "number | null"
    elif kind == "point":
        value_type = "GeoPoint | null"
    else:
        value_type = "string | null"
    plan = FieldPlan(
        name=name,
        key=key,
        element_id=form_field.id,
        widget=widget,
        label=form_field.label or value.label or label(name),
        kind=kind,
        value_type=value_type,
        empty=_EMPTY.get(kind, "null"),
        input_type=_INPUT_TYPES.get(value.type, "text"),
        required_message="Select a value."
        if kind in ("enum", "date", "datetime")
        else "Enter a latitude and a longitude."
        if kind == "point"
        else "Enter a value.",
    )
    if kind == "enum":
        plan.value_type = "(" + " | ".join(js(v) for v in value.values or []) + ") | null"
        plan.options = (
            "["
            + ", ".join(
                f"{{ value: {js(v)}, label: {text_js(label(v))} }}" for v in value.values or []
            )
            + "]"
        )
    if value.type == "integer":
        plan.step = 1
    if widget == "number" and value.format in NUMBER_FORMATS:
        plan.format = value.format
        plan.currency = value.currency if value.format == "currency" else None
    return plan


def _file_field(name: str, key: str, form_field: FormField, value: Field, widget: str) -> FieldPlan:
    """Return the plan of a file field: the widget checks the size and the type of a new file."""
    types = value.media_types
    rule = f"{snake(key).upper()}_FILE_RULE"
    plan = FieldPlan(
        name=name,
        key=key,
        element_id=form_field.id,
        widget=widget,
        label=form_field.label or value.label or label(name),
        kind="file",
        value_type="File | FileValue | null",
        empty="null",
        required_message="Select a file.",
        file_rule=f"{{ maxSize: {value.size_limit}, types: {js(types)} }}",
    )
    new = f"values.{key} instanceof File"
    plan.checks.append(
        Check(
            f"{new} && values.{key}.size > {rule}.maxSize",
            f"The file is larger than {format_size(value.size_limit)}.",
            value.id,
        )
    )
    if types:
        plan.checks.append(
            Check(
                f"{new} && !fileAllowed(values.{key}, {rule}.types)",
                f"Select a file of a type that the field allows: {', '.join(types)}.",
                value.id,
            )
        )
    return plan


def _widget_options(plan: FieldPlan, form_field: FormField) -> None:
    plan.placeholder = form_field.placeholder
    plan.help = form_field.help
    plan.span = form_field.span
    plan.rows = form_field.rows
    if form_field.step is not None:
        plan.step = form_field.step


def _to_input(plan: FieldPlan, nullable: bool, required: bool) -> str:
    """Return the input value of a field: an empty value becomes null or undefined."""
    value = f"values.{plan.key}"
    empty = "null" if nullable else "undefined"
    if plan.kind == "text":
        if required:
            return f"{value}.trim()"
        return f'{value}.trim() === "" ? {empty} : {value}.trim()'
    if plan.kind in ("many", "boolean") or required:
        return value
    return f"{value} ?? {empty}"


def _initial(plan: FieldPlan, default: Any, update: bool, member: Member | None) -> str:
    """Return the initial value: the record, the form default, the field default, or empty."""
    if plan.kind == "file":
        return f"record ? (record.{plan.key} ?? null) : null" if update else "null"
    fallback = plan.empty
    if isinstance(default, str) and default.startswith("$route."):
        param = default.removeprefix("$route.")
        fallback = f"routeParams?.[{js(param)}] ?? {plan.empty}"
    elif default == ME:
        fallback = "me === null ? [] : [me]" if plan.kind == "many" else f"me ?? {plan.empty}"
    elif default is not None:
        fallback = _literal(plan, default)
    elif member is not None and member.default is not None and member.default != []:
        fallback = _literal(plan, member.default)
    if update and member is not None:
        if plan.kind == "text":
            return f'record ? String(record.{plan.key} ?? "") : {fallback}'
        return f"record ? (record.{plan.key} ?? {plan.empty}) : {fallback}"
    return fallback


def _translations(definition: AppDefinition, plan: FieldPlan, update: bool) -> None:
    """Give a translatable field a widget for each other language (ADR 0026).

    The record has the values of all languages in `<field>Translations`.
    The input gives them all, so that the value of each language is the
    value of its widget, in each selected language.
    """
    i18n = i18n_plan(definition)
    if i18n is None:
        return
    key = translations_key(plan.name)
    plan.languages = i18n.others
    plan.translations_key = key
    default = js(i18n.default)
    if update:
        # The field of the record has the value of the selected language.
        plan.initial = plan.initial.replace(
            f"record.{plan.key} ??", f"record.{key}?.[{default}] ?? record.{plan.key} ??", 1
        )
    codes = [js(language.code) for language in plan.languages]
    initial = [
        f'{code}: record ? String(record.{key}?.[{code}] ?? "") : ""' if update else f'{code}: ""'
        for code in codes
    ]
    plan.translations_initial = "{ " + ", ".join(initial) + " }"
    values = [f"{default}: values.{plan.key}.trim() || null"]
    values += [f"{code}: values.{key}[{code}]?.trim() || null" for code in codes]
    plan.translations_input = "{ " + ", ".join(values) + " }"


def _input_keys(fields: list[FieldPlan]) -> list[str]:
    """Return the keys of the input of the fields: a translatable field has two keys, and a file
    field and a lines editor none."""
    keys: list[str] = []
    for f in fields:
        if f.kind in ("file", "lines"):
            continue
        keys.append(f.key)
        if f.translations_key:
            keys.append(f.translations_key)
    return keys


def _schema(schema: str, keys: list[str]) -> str:
    """Return the zod schema of the input of the fields: the keys of the schema of the entity."""
    return f"{schema}.pick({{ {', '.join(f'{key}: true' for key in keys)} }})"


def _literal(plan: FieldPlan, value: Any) -> str:
    if plan.kind == "text":
        return js(str(value))
    return js(value)


def _rules(plan: FieldPlan, form_field: FormField) -> None:
    rules = form_field.rules
    if rules is None:
        return
    plan.rules_id = rules.id
    value = f"values.{plan.key}"
    if rules.required is not None:
        plan.required = True
        plan.required_id = rules.required.id
        if rules.required.message:
            plan.required_message = rules.required.message
    text = plan.kind == "text"
    if rules.min_length is not None and text:
        n = rules.min_length.value
        plan.checks.append(
            Check(
                f'{value}.trim() !== "" && {value}.trim().length < {n}',
                rules.min_length.message or f"Use {n} or more characters.",
                rules.min_length.id,
            )
        )
    if rules.max_length is not None and text:
        n = rules.max_length.value
        plan.checks.append(
            Check(
                f"{value}.trim().length > {n}",
                rules.max_length.message or f"Use {n} or fewer characters.",
                rules.max_length.id,
            )
        )
    if rules.pattern is not None and text:
        plan.checks.append(
            Check(
                f'{value}.trim() !== "" && '
                f"!new RegExp({js(rules.pattern.value)}).test({value}.trim())",
                rules.pattern.message or "Use the correct format.",
                rules.pattern.id,
            )
        )
    for rule, op, word in ((rules.min, "<", "or more"), (rules.max, ">", "or less")):
        if rule is not None and plan.kind == "number":
            plan.checks.append(
                Check(
                    f"{value} !== null && {value} {op} {_number(rule.value)}",
                    rule.message or f"Use {_number(rule.value)} {word}.",
                    rule.id,
                )
            )


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _form_rule(
    definition: AppDefinition,
    rule: CompareRule | CustomRule,
    by_field: dict[str, FieldPlan],
) -> FormRulePlan:
    if isinstance(rule, CompareRule):
        a, b = by_field[rule.field].key, by_field[rule.other].key
        condition = f"!compareRule(values.{a}, {js(rule.op)}, values.{b})"
        return FormRulePlan(rule.id, [a], rule.message, condition=condition)
    spec = gap_spec(definition, rule.id, "custom_rule")
    return FormRulePlan(
        rule.id,
        [by_field[f].key for f in rule.fields],
        rule.message or "Check the values.",
        gap_module=spec.module + ".gen",
        gap_name=spec.name,
    )


def _record_param(definition: AppDefinition, page_name: str) -> str | None:
    """Return the last path parameter of a page: the ID of its record."""
    path = definition.pages[page_name].path
    params = [part[1:-1] for part in path.split("/") if part.startswith("{")]
    return params[-1] if params else None


def _grid(grid: Grid | None) -> str:
    if grid is None:
        return "grid grid-cols-1 gap-4"
    classes = ["grid", f"grid-cols-{grid.columns}"]
    classes.append(f"gap-{css_class_var(grid.gap)}" if grid.gap else "gap-4")
    for breakpoint, override in grid.responsive.items():
        if override.columns:
            classes.append(f"max-{breakpoint}:grid-cols-{override.columns}")
        if override.gap:
            classes.append(f"max-{breakpoint}:gap-{css_class_var(override.gap)}")
    return " ".join(classes)


def _span_classes(span: int, grid: Grid | None) -> str:
    """Return the span of a field: no more columns than the grid has at each breakpoint."""
    columns = grid.columns if grid else 1
    span = min(span, columns)
    if span <= 1:
        return ""
    classes = [f"col-span-{span}"]
    for breakpoint, override in grid.responsive.items() if grid else ():
        if override.columns and override.columns < span:
            classes.append(f"max-{breakpoint}:col-span-{override.columns}")
    return " ".join(classes)


def _navigate(
    definition: AppDefinition, form: Form, entity: str, operation: Operation
) -> str | None:
    """Return the path to open after a success, of `result` (the record of the operation)."""
    on_success = form.on_success
    if on_success is None or on_success.navigate is None:
        return None
    page = definition.pages[on_success.navigate]
    params = [part[1:-1] for part in page.path.split("/") if part.startswith("{")]
    page_name = js(camel(on_success.navigate))
    if not params:
        return f"pageHref({page_name})"
    returns_record = operation.kind != "custom" or operation.returns == entity
    if len(params) == 1 and page.entity == entity and returns_record:
        return f"pageHref({page_name}, {{ {params[0]}: result.id }})"
    return None


HELPERS: dict[str, Callable[..., Any]] = {}
"""The helpers of the form templates."""


_FORM = "src/features/{{ name | kebab }}-form"
# The view rules write these runtime files when the app has list views.
_FORMS_ONLY = "ui_forms.used and not ui_views.list_views"


def form_rules() -> tuple[Output, ...]:
    """Return the output rules of the forms.

    Each form is a feature slice in `src/features/<form>-form`. The runtime
    files of the form widgets are in the app only if a form needs them. The
    bindings that use the forms put `FormContext` in their context as
    `ui_forms`, next to `ViewContext` as `ui_views`, use `view_rules()`
    too, and give each entity the zod schemas `<Entity>InputSchema` and
    `<Entity>PatchSchema`.
    """
    return (
        Output(
            template="ui/views/lib/format.ts.j2", path="src/shared/lib/format.ts", when=_FORMS_ONLY
        ),
        Output(
            template="ui/views/lib/query.ts.j2", path="src/shared/lib/query.ts", when=_FORMS_ONLY
        ),
        Output(
            template="ui/forms/lib/form.ts.j2", path="src/shared/lib/form.ts", when="ui_forms.used"
        ),
        # The totals of the lines of a form compute the preview of a field (ADR 0034).
        Output(
            template="ui/views/lib/compute.ts.j2",
            path="src/shared/lib/compute.ts",
            when="ui_forms.previews and not ui_views.computed",
        ),
        *(
            Output(
                template=f"ui/forms/widgets/{part}.tsx.j2",
                path=f"src/shared/ui/form-widgets/{part}.tsx",
                when=when,
            )
            for part, when in (
                ("option-select", "ui_forms.used"),
                ("option-radio", "'radio' in ui_forms.widgets"),
                ("date-input", "'date' in ui_forms.widgets or 'datetime' in ui_forms.widgets"),
                ("date-time-input", "'datetime' in ui_forms.widgets"),
                ("number-input", "'number_format' in ui_forms.widgets"),
                ("relation-select", "ui_forms.relations"),
                ("file-input", "ui_forms.files"),
                ("point-input", "'point' in ui_forms.widgets"),
                ("mention-textarea", "'mentions' in ui_forms.widgets"),
            )
        ),
        Output(
            template="ui/forms/form.tsx.j2",
            path=_FORM + "/ui/{{ name | kebab }}-form.tsx",
            for_each="form",
        ),
        Output(template="ui/forms/index.ts.j2", path=_FORM + "/index.ts", for_each="form"),
    )
