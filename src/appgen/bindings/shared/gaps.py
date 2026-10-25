"""Generation gaps of the Next.js and the React apps (ADR 0005).

Each custom element of the definition gets a generated file and an
extension file next to it. The generated file has the generated trace
and calls the extension code. The extension file has the gap trace and
a stub with a `TODO(appgen):` comment. appgen creates it once, and the
app builds with the stub. The paths are the same in both apps, so that
the shared UI templates can import the files.

The files of each kind of element, without the `.gen` or `.ext` suffix:

- Custom operation: `src/features/<op>/api/<op>` (`.ts`). The params type
  is in the entity slice. In the Next.js app, the generated file is the
  server action.
- Custom page content: `src/pages/<page>/ui/<page>-content` (`.tsx`).
- Custom detail tab: `src/widgets/<view>/ui/<tab>-tab` (`.tsx`).
- Custom detail section: `src/widgets/<view>/ui/[<tab>-]<section>-section`
  (`.tsx`).
- Custom dashboard widget: `src/widgets/<dashboard>/ui/<widget>-widget`
  (`.tsx`).
- Custom form widget: `src/features/<form>-form/ui/<field>-widget` (`.tsx`).
- Custom form rule: `src/features/<form>-form/model/<rule>-rule` (`.ts`).
- Custom action: `src/features/<owner>-actions/model/[row-|bulk-]<action>-action`
  (`.ts`). The owner is the view, the page, or the layout.
"""

from dataclasses import dataclass, field

from appgen.bindings.shared.typescript import members, param_type
from appgen.dsl.model import AppDefinition, Field, Operation
from appgen.dsl.ui.views import ViewBase
from appgen.gen.binding import Output
from appgen.gen.naming import camel, kebab, pascal

_TS_TYPES = {
    "integer": "number",
    "decimal": "number",
    "boolean": "boolean",
    "json": "unknown",
}


@dataclass(frozen=True, slots=True)
class GapSpec:
    """What the files of one generation gap contain."""

    element_id: str
    base: str
    """The path of the files without the suffix, for example `src/widgets/x/ui/y-tab`."""
    name: str
    """The name that the files export, for example `ActivityTab`."""
    what: str
    """A short text for the TODO comment, for example `the content of the tab activity`."""
    imports: list[str] = field(default_factory=list[str])
    """The import lines that the types need."""
    params: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """The parameters of the function or the props of the component: (name, TypeScript type)."""
    returns: str = "void"

    @property
    def module(self) -> str:
        """The import path of the files, without the suffix: `@/widgets/x/ui/y-tab`."""
        return "@/" + self.base.removeprefix("src/")

    @property
    def file(self) -> str:
        """The file name without the folder and the suffix."""
        return self.base.rsplit("/", 1)[-1]


def _entity_import(entity: str, *names: str) -> str:
    return f'import type {{ {", ".join(names)} }} from "@/entities/{kebab(entity)}";'


def _ts_type(definition: AppDefinition, entity: str, member: Field | None, name: str) -> str:
    if member is None:
        found = {m.name: m for m in members(entity, definition.entities[entity])}.get(name)
        return found.ts_type if found else "unknown"
    if member.type == "enum":
        return " | ".join(f'"{value}"' for value in member.values or [])
    return _TS_TYPES.get(member.type, "string")


def operation_gap(definition: AppDefinition, name: str) -> GapSpec:
    """Return the gap of a custom operation: a function of the record and the params."""
    operation: Operation = definition.operations[name]
    entity = operation.entity
    imports = [_entity_import(entity, pascal(entity))]
    returns = "void"
    if operation.returns != "none":
        returns = pascal(operation.returns)
        if operation.returns != entity:
            imports.append(_entity_import(operation.returns, returns))
    params = [("record", pascal(entity))]
    if operation.params:
        imports[0] = _entity_import(entity, pascal(entity), f"{pascal(name)}Params")
        params.append(("params", f"{pascal(name)}Params"))
    return GapSpec(
        element_id=operation.id,
        base=f"src/features/{kebab(name)}/api/{kebab(name)}",
        name=camel(name),
        what=f"the logic of the operation {name}",
        imports=imports,
        params=params,
        returns=f"Promise<{returns}>",
    )


def component_gap(definition: AppDefinition, element_id: str) -> GapSpec:
    """Return the gap of a custom UI part: a page content, a tab, a section, or a widget."""
    parts = element_id.split(".")
    if parts[0] == "pages":
        page_name = parts[1]
        page = definition.pages[page_name]
        imports: list[str] = []
        params: list[tuple[str, str]] = []
        if page.entity:
            params = [("params", "Readonly<Record<string, string | undefined>>")]
        return GapSpec(
            element_id=element_id,
            base=f"src/pages/{kebab(page_name)}/ui/{kebab(page_name)}-content",
            name=f"{pascal(page_name)}Content",
            what=f"the content of the page {page_name}",
            imports=imports,
            params=params,
        )
    if parts[1] == "dashboards":
        dashboard, widget = parts[2], parts[4]
        return GapSpec(
            element_id=element_id,
            base=f"src/widgets/{kebab(dashboard)}/ui/{kebab(widget)}-widget",
            name=f"{pascal(widget)}Widget",
            what=f"the widget {widget} of the dashboard {dashboard}",
        )
    if parts[1] == "forms":
        return _form_widget_gap(definition, element_id, parts[2], parts[4])
    view_name = parts[2]
    assert definition.ui is not None
    view = definition.ui.views[view_name]
    # A view of API data has no custom parts.
    assert isinstance(view, ViewBase)
    entity = view.entity
    imports = [_entity_import(entity, pascal(entity))]
    params = [("record", pascal(entity))]
    if parts[3] == "tabs" and len(parts) == 5:
        tab = parts[4]
        return GapSpec(
            element_id=element_id,
            base=f"src/widgets/{kebab(view_name)}/ui/{kebab(tab)}-tab",
            name=f"{pascal(tab)}Tab",
            what=f"the tab {tab} of the view {view_name}",
            imports=imports,
            params=params,
        )
    section = parts[-1]
    prefix = f"{kebab(parts[4])}-" if parts[3] == "tabs" else ""
    return GapSpec(
        element_id=element_id,
        base=f"src/widgets/{kebab(view_name)}/ui/{prefix}{kebab(section)}-section",
        name=f"{pascal(parts[4]) if prefix else ''}{pascal(section)}Section",
        what=f"the section {section} of the view {view_name}",
        imports=imports,
        params=params,
    )


def _form_widget_gap(
    definition: AppDefinition, element_id: str, form_name: str, field_name: str
) -> GapSpec:
    assert definition.ui is not None
    form = definition.ui.forms[form_name]
    operation = definition.operations.get(form.operation)
    if operation is not None and operation.kind == "custom":
        value_type = param_type(operation.params[field_name])
    else:
        member = definition.entities[form.entity].fields.get(field_name)
        value_type = _ts_type(definition, form.entity, member, field_name)
    return GapSpec(
        element_id=element_id,
        base=f"src/features/{kebab(form_name)}-form/ui/{kebab(field_name)}-widget",
        name=f"{pascal(field_name)}Widget",
        what=f"the widget of the field {field_name} of the form {form_name}",
        params=[
            ("id", "string"),
            ("value", f"{value_type} | null"),
            ("onChange", f"(value: {value_type} | null) => void"),
            ("disabled", "boolean"),
        ],
    )


def form_values(definition: AppDefinition, form_name: str) -> tuple[str, str]:
    """Return the TypeScript type of the values of a form, and its import line."""
    assert definition.ui is not None
    form = definition.ui.forms[form_name]
    operation = definition.operations.get(form.operation)
    if operation is not None and operation.kind == "custom" and operation.params:
        type_name = f"{pascal(form.operation)}Params"
        return type_name, _entity_import(form.entity, type_name)
    type_name = f"{pascal(form.entity)}Input"
    return f"Partial<{type_name}>", _entity_import(form.entity, type_name)


def rule_gap(definition: AppDefinition, element_id: str) -> GapSpec:
    """Return the gap of a custom form rule: a check of the form values."""
    form_name, rule = element_id.split(".")[2], element_id.split(".")[4]
    values_type, values_import = form_values(definition, form_name)
    return GapSpec(
        element_id=element_id,
        base=f"src/features/{kebab(form_name)}-form/model/{kebab(rule)}-rule",
        name=f"{camel(rule)}Rule",
        what=f"the rule {rule} of the form {form_name}",
        imports=[values_import],
        params=[("values", values_type)],
        returns="boolean",
    )


def action_gap(definition: AppDefinition, element_id: str) -> GapSpec:
    """Return the gap of a custom action: a function of the record or the records."""
    parts = element_id.split(".")
    action = parts[-1]
    group = parts[-2]
    entity: str | None = None
    if parts[0] == "pages":
        owner = parts[1]
        page = definition.pages[owner]
        entity = page.entity if "{" in page.path else None
    elif parts[1] == "layouts":
        owner = parts[2]
    else:
        owner = parts[2]
        assert definition.ui is not None
        view = definition.ui.views[owner]
        # A view of API data has no actions.
        assert isinstance(view, ViewBase)
        is_record = group in ("row_actions", "bulk_actions") or view.kind == "detail"
        entity = view.entity if is_record else None
    prefix = {"row_actions": "row-", "bulk_actions": "bulk-"}.get(group, "")
    imports: list[str] = []
    params: list[tuple[str, str]] = []
    if entity is not None:
        imports.append(_entity_import(entity, pascal(entity)))
        many = group == "bulk_actions"
        params.append(("records" if many else "record", pascal(entity) + ("[]" if many else "")))
    return GapSpec(
        element_id=element_id,
        base=f"src/features/{kebab(owner)}-actions/model/{prefix}{kebab(action)}-action",
        name=f"run{pascal(prefix.rstrip('-'))}{pascal(action)}Action",
        what=f"the action {action} of {owner}",
        imports=imports,
        params=params,
        returns="Promise<void>",
    )


def gap_spec(definition: AppDefinition, element_id: str, kind: str) -> GapSpec:
    """Return the gap of a custom element of any kind."""
    if kind == "operation":
        return operation_gap(definition, element_id.split(".")[1])
    if kind == "custom_rule":
        return rule_gap(definition, element_id)
    if kind == "custom_action":
        return action_gap(definition, element_id)
    return component_gap(definition, element_id)


COMPONENT_GAPS: tuple[tuple[str, str | None], ...] = (
    ("page_content", "element.custom"),
    ("detail_tab", "element.custom"),
    ("detail_section", "element.custom"),
    ("custom_widget", None),
    ("form_field", "element.widget == 'custom'"),
)
"""The element kinds with a component gap, and the condition of the gap."""

FUNCTION_GAPS: tuple[str, ...] = ("custom_rule", "custom_action")
"""The element kinds with a function gap."""

_GAP = "{{ gap_spec(definition, element_id, element_kind).base }}"


def gap_rules() -> list[Output]:
    """Return the output rules of the component and the function gaps.

    Each gap has a generated file (`.gen`) and an extension file (`.ext`)
    from the shared templates in `gap/`. A binding adds `gap_spec` to its
    template helpers.
    """
    kinds = [("component", "tsx", kind, when) for kind, when in COMPONENT_GAPS]
    kinds += [("function", "ts", kind, None) for kind in FUNCTION_GAPS]
    return [
        Output(
            template=f"gap/{template}.{part}.{suffix}.j2",
            path=f"{_GAP}.{part}.{suffix}",
            for_each=kind,
            when=when,
            extension=part == "ext",
        )
        for template, suffix, kind, when in kinds
        for part in ("gen", "ext")
    ]
