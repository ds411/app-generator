"""The forms of the front-end apps: create, edit, and custom operation forms (ADR 0003).

The shared UI templates in `templates/ui/forms/` render the `FormPlan` of
each form. A form keeps the values of its widgets in a `Values` object:
text as a string (empty: `""`), numbers, dates, enum values, and single
relations as a value or `null`, many-to-many relations as a list of IDs,
and booleans. On submit, the form turns the values into the input of its
operation, checks the input with the zod schema of the entity slice and
with the rules of the form, and calls the operation.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from appgen.bindings.shared.gaps import form_values, gap_spec
from appgen.bindings.shared.typescript import Member, members
from appgen.bindings.shared.ui import css_class_var, js
from appgen.bindings.shared.views import definition_display, label
from appgen.dsl.model import AppDefinition, Field, Operation
from appgen.dsl.ui.common import Grid
from appgen.dsl.ui.fields import FieldTarget, default_widget, resolve_path
from appgen.dsl.ui.forms import CompareRule, CustomRule, Form, FormField
from appgen.gen.binding import Output
from appgen.gen.naming import camel, kebab, pascal

type ValueKind = Literal[
    "text", "number", "enum", "one", "many", "boolean", "date", "datetime", "json"
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
}
_EMPTY: dict[ValueKind, str] = {
    "text": '""',
    "many": "[]",
    "boolean": "false",
}
_INPUT_TYPES = {"email": "email", "url": "url"}


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
    initial: str = ""
    """The TypeScript initial value, of `record` and `routeParams`."""
    checks: list[Check] = field(default_factory=list[Check])
    rules_id: str | None = None
    gap_module: str | None = None
    gap_name: str | None = None
    classes: str = ""
    """The grid classes of the field: its span, with the responsive overrides."""


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
    """The target entities of the relation fields, sorted by name."""
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
    widgets: set[str] = field(default_factory=set[str])
    """The widgets that the form uses."""

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


class FormContext:
    """The form plans of a definition, for the form templates and the actions."""

    def __init__(self, definition: AppDefinition) -> None:
        self.definition = definition
        ui = definition.ui
        self.names: list[str] = list(ui.forms) if ui else []
        self._plans: dict[str, FormPlan] = {}

    def plan(self, name: str) -> FormPlan:
        """Return the plan of a form."""
        if name not in self._plans:
            self._plans[name] = _build(self.definition, name)
        return self._plans[name]

    @property
    def widgets(self) -> set[str]:
        """Return the widgets of all forms, for the runtime files and the components."""
        return {w for name in self.names for w in self.plan(name).widgets}

    @property
    def relations(self) -> bool:
        """Return True if a form has a relation field."""
        return any(f.target for name in self.names for f in self.plan(name).fields)


def _build(definition: AppDefinition, name: str) -> FormPlan:
    assert definition.ui is not None
    form = definition.ui.forms[name]
    entity = form.entity
    operation: Operation = definition.operations[form.operation]
    params = operation.params if operation.kind == "custom" else None
    by_name = {m.name: m for m in members(entity, definition.entities[entity])}
    fields: list[FieldPlan] = []
    route_params = False
    for field_name, form_field in form.fields.items():
        default = form.defaults.get(field_name)
        if isinstance(default, str) and default.startswith("$route."):
            route_params = True
        if params is not None and field_name in params:
            plan = _param_field(field_name, form_field, params[field_name])
        else:
            plan = _member_field(definition, entity, field_name, form_field, by_name[field_name])
        plan.initial = _initial(plan, default, operation.kind == "update", by_name.get(field_name))
        _rules(plan, form_field)
        if plan.widget == "custom":
            spec = gap_spec(definition, form_field.id, "form_field")
            plan.gap_module = spec.module + ".gen"
            plan.gap_name = spec.name
        plan.classes = _span_classes(form_field.span, form.grid)
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
        call = (
            f"{op}(input as {type_name}Input)"
            if operation.kind == "create"
            else f"{op}(record.id, input)"
        )
    imports.insert(0, f'import {{ {", ".join(entity_names)} }} from "@/entities/{kebab_entity}";')
    for rule in rules:
        if rule.gap_name:
            imports.append(f'import {{ {rule.gap_name} }} from "{rule.gap_module}";')
    for f in fields:
        if f.gap_name:
            imports.append(f'import {{ {f.gap_name} }} from "{f.gap_module}";')
    lookups = sorted({f.target for f in fields if f.target})
    host = next(
        (
            p_name
            for p_name, page in definition.pages.items()
            if page.content is not None and page.content.form == name
        ),
        None,
    )
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
        schema=f"{schema}.pick({{ {', '.join(f'{f.key}: true' for f in fields)} }})",
        input_type=input_type,
        call=call,
        imports=imports,
        lookups=lookups,
        host_page=host,
        record_param=_record_param(definition, host) if host else None,
        navigate=_navigate(definition, form, entity, operation),
        rule_values=form_values(definition, name)[0],
        route_params=route_params,
        widgets={f.widget for f in fields},
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
    kind = _KINDS[value.type]
    if kind == "text":
        value_type = "string"
    elif kind == "json":
        value_type = "unknown"
    elif kind == "boolean":
        value_type = "boolean"
    elif kind == "number":
        value_type = "number | null"
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
        else "Enter a value.",
    )
    if kind == "enum":
        plan.value_type = "(" + " | ".join(js(v) for v in value.values or []) + ") | null"
        plan.options = (
            "["
            + ", ".join(f"{{ value: {js(v)}, label: {js(label(v))} }}" for v in value.values or [])
            + "]"
        )
    if value.type == "integer":
        plan.step = 1
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
    fallback = plan.empty
    if isinstance(default, str) and default.startswith("$route."):
        param = default.removeprefix("$route.")
        fallback = f"routeParams?.[{js(param)}] ?? {plan.empty}"
    elif default is not None:
        fallback = _literal(plan, default)
    elif member is not None and member.default is not None and member.default != []:
        fallback = _literal(plan, member.default)
    if update and member is not None:
        if plan.kind == "text":
            return f'record ? String(record.{plan.key} ?? "") : {fallback}'
        return f"record ? (record.{plan.key} ?? {plan.empty}) : {fallback}"
    return fallback


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
_FORMS_ONLY = "ui_forms.names and not ui_views.list_views"


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
            template="ui/forms/lib/form.ts.j2", path="src/shared/lib/form.ts", when="ui_forms.names"
        ),
        *(
            Output(
                template=f"ui/forms/widgets/{part}.tsx.j2",
                path=f"src/shared/ui/form-widgets/{part}.tsx",
                when=when,
            )
            for part, when in (
                ("option-select", "ui_forms.names"),
                ("option-radio", "'radio' in ui_forms.widgets"),
                ("date-input", "'date' in ui_forms.widgets or 'datetime' in ui_forms.widgets"),
                ("date-time-input", "'datetime' in ui_forms.widgets"),
                ("relation-select", "ui_forms.relations"),
            )
        ),
        Output(
            template="ui/forms/form.tsx.j2",
            path=_FORM + "/ui/{{ name | kebab }}-form.tsx",
            for_each="form",
        ),
        Output(template="ui/forms/index.ts.j2", path=_FORM + "/index.ts", for_each="form"),
    )
