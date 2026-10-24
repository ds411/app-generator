"""The shadcn/ui components that a definition uses (ADR 0003, "Binding map").

The component templates are in `templates/shadcn/`. `scripts/vendor_shadcn.py`
copies them from a fixed commit of shadcn/ui and writes `registry.json`:
the npm packages, the other components, and the hooks of each component.
The front-end bindings write only the components that the UI of the
definition needs, and the npm packages of these components.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from appgen.bindings.shared import TEMPLATE_DIR
from appgen.dsl.model import AppDefinition, Field
from appgen.dsl.ui.common import Action
from appgen.dsl.ui.dashboards import ChartWidget, ListWidget, StatWidget
from appgen.dsl.ui.fields import FieldPathError, FieldTarget, default_widget, resolve_path
from appgen.dsl.ui.forms import Form
from appgen.dsl.ui.views import (
    BoardView,
    CalendarView,
    CardsView,
    TableView,
    View,
)

BASE_COMPONENTS = ("button", "sonner")
"""The components that each app has: buttons, and the toasts of the actions."""

_WIDGET_COMPONENTS: dict[str, tuple[str, ...]] = {
    "text": ("input",),
    "textarea": ("textarea",),
    "number": ("input",),
    "select": ("select",),
    "radio": ("radio-group",),
    "checkbox": ("checkbox",),
    "switch": ("switch",),
    "date": ("popover", "calendar"),
    "datetime": ("popover", "calendar", "input"),
    "relation": ("popover", "command", "badge"),
    "custom": (),
}
# A form in `page` mode without a page that shows it opens in a dialog.
_FORM_MODES: dict[str, tuple[str, ...]] = {
    "dialog": ("dialog",),
    "sheet": ("sheet",),
    "page": ("dialog",),
}


@dataclass(frozen=True, slots=True)
class Component:
    """A shadcn/ui component, as `registry.json` describes it."""

    name: str
    dependencies: tuple[str, ...]
    """The npm packages that the component imports."""
    components: tuple[str, ...]
    """The other components that the component imports."""
    hooks: tuple[str, ...]
    """The hooks in `@/shared/lib` that the component imports, for example `use-mobile`."""

    @property
    def template(self) -> str:
        """The name of the template of the component in the shared templates."""
        return f"shadcn/{self.name}.tsx.j2"


@cache
def registry() -> dict[str, Component]:
    """Return the shadcn/ui components that the shared templates have, by name."""
    data = json.loads((TEMPLATE_DIR / "shadcn" / "registry.json").read_text(encoding="utf-8"))
    return {
        name: Component(
            name=name,
            dependencies=tuple(item["dependencies"]),
            components=tuple(item["components"]),
            hooks=tuple(item["hooks"]),
        )
        for name, item in data["components"].items()
    }


def with_dependencies(names: Iterable[str]) -> list[Component]:
    """Return the components and all the components that they import, sorted by name."""
    components = registry()
    todo = list(names)
    found: dict[str, Component] = {}
    while todo:
        name = todo.pop()
        if name not in found:
            found[name] = components[name]
            todo.extend(found[name].components)
    return [found[name] for name in sorted(found)]


def packages(components: Iterable[Component]) -> list[str]:
    """Return the npm packages of the components, sorted by name."""
    return sorted({package for component in components for package in component.dependencies})


def hooks(components: Iterable[Component]) -> list[str]:
    """Return the hooks of the components, sorted by name."""
    return sorted({hook for component in components for hook in component.hooks})


def has_mode_toggle(definition: AppDefinition) -> bool:
    """Return True if the app shows a switch for the color mode (ADR 0003, "Theme")."""
    ui = definition.ui
    if ui is None or (ui.theme is not None and not ui.theme.mode_toggle):
        return False
    topbars = [layout.topbar for layout in ui.layouts.values() if layout.topbar is not None]
    return not topbars or any(topbar.mode_toggle for topbar in topbars)


def used_components(definition: AppDefinition) -> list[Component]:
    """Return the components that the UI of a definition needs, with their dependencies."""
    names: set[str] = set(BASE_COMPONENTS)
    ui = definition.ui
    if ui is not None:
        if has_mode_toggle(definition):
            names.add("dropdown-menu")
        for layout in ui.layouts.values():
            if layout.sidebar is not None:
                names.update(("sidebar", "separator"))
            if layout.topbar is not None:
                names.add("separator")
                overrides = [o.topbar for o in layout.responsive.values() if o.topbar is not None]
                if layout.topbar.breadcrumbs or any(o.breadcrumbs for o in overrides):
                    names.update(("breadcrumb", "skeleton"))
                if layout.topbar.search or any(o.search for o in overrides):
                    names.update(("command", "dialog"))
                names.update(_action_components(layout.topbar.actions.values()))
        if any(g.collapsible for menu in ui.navigation.values() for g in menu.groups.values()):
            names.add("collapsible")
        if ui.badges:
            names.add("badge")
        for view in ui.views.values():
            names.update(_view_components(view))
        names.update(_list_components(definition))
        for form in ui.forms.values():
            names.update(_form_components(definition, form))
        for dashboard in ui.dashboards.values():
            for widget in dashboard.widgets.values():
                if isinstance(widget, StatWidget):
                    names.add("card")
                elif isinstance(widget, ChartWidget):
                    names.update(("card", "chart"))
                elif isinstance(widget, ListWidget):
                    names.add("card")
        names.update(("skeleton", "spinner", "empty"))
    for page in definition.pages.values():
        names.update(_action_components(page.actions.values()))
    return with_dependencies(names)


def _action_components(actions: Iterable[Action]) -> set[str]:
    names: set[str] = set()
    for action in actions:
        if action.confirm is not None:
            names.add("alert-dialog")
    return names


def _view_components(view: View) -> set[str]:
    """Return the components of a detail view. The list views come from `_list_components`."""
    names = _action_components(view.actions.values())
    if isinstance(view, TableView | CardsView | BoardView | CalendarView):
        return names
    names.update(("card", "separator"))
    if view.tabs:
        names.add("tabs")
    if view.header is not None and view.header.badges:
        names.add("badge")
    return names


# The components of each part of the list views (see `ViewContext.features`).
_LIST_COMPONENTS: dict[str, tuple[str, ...]] = {
    "table": ("table", "checkbox", "select"),
    "cards": ("card", "select"),
    "board": ("card", "badge", "scroll-area"),
    "calendar": ("button",),
    "search": ("input",),
    "boolean": ("switch",),
    "date_range": ("popover", "calendar"),
    "select": ("select",),
    "multi_select": ("popover", "command"),
    "badge": ("badge",),
    "avatar": ("avatar",),
}


def _list_components(definition: AppDefinition) -> set[str]:
    """Return the components of the list views and of their shared runtime files."""
    # A local import: the views module imports this module through `ui`.
    from appgen.bindings.shared.views import ViewContext

    context = ViewContext(definition)
    if not context.runtime:
        return set()
    # The actions, the states, and the page controls of all views.
    names = {"alert-dialog", "dropdown-menu", "empty", "skeleton", "spinner"}
    for feature in context.features:
        names.update(_LIST_COMPONENTS.get(feature, ()))
    return names


def _form_components(definition: AppDefinition, form: Form) -> set[str]:
    names = {"field", "label", "spinner", *_FORM_MODES[form.mode]}
    operation = definition.operations.get(form.operation)
    params = operation.params if operation is not None and operation.kind == "custom" else None
    for name, form_field in form.fields.items():
        widget = form_field.widget
        if widget is None:
            widget = _default_widget(definition, form.entity, name, params)
        names.update(_WIDGET_COMPONENTS.get(widget or "custom", ()))
        if widget == "number" and _has_format(definition, form.entity, name, params):
            names.add("input-group")
    return names


def _has_format(
    definition: AppDefinition, entity: str, name: str, params: dict[str, Field] | None
) -> bool:
    """Return True if a number field of a form has a number format (see `NumberInput`)."""
    if params is not None and name in params:
        member: object = params[name]
    else:
        try:
            member = resolve_path(definition, entity, name).member
        except FieldPathError:
            return False
    return isinstance(member, Field) and member.format in ("number", "currency", "percent")


def _default_widget(
    definition: AppDefinition, entity: str, name: str, params: dict[str, Field] | None
) -> str | None:
    if params is not None:
        param = params.get(name)
        return default_widget(FieldTarget(entity, name, param)) if param is not None else None
    try:
        return default_widget(resolve_path(definition, entity, name))
    except FieldPathError:
        return None
