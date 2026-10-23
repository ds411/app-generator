from textwrap import dedent

import pytest

from appgen.dsl import AppDefinition, DefinitionError, Diagnostic, Location, load_definition_text
from appgen.dsl.ui.common import FormAction, NavigateAction, OperationAction
from appgen.dsl.ui.layout import Layout, Menu, MenuGroup, MenuItem
from appgen.dsl.ui.routes import Breadcrumb, breadcrumbs, page_parent

VALID = dedent(
    """\
    version: 0
    app: { name: demo, title: Demo }
    entities:
      Project:
        display_field: name
        fields:
          name: { type: string }
    operations:
      delete_project: { kind: delete, entity: Project }
    pages:
      dashboard: { path: /, title: Dashboard, content: { dashboard: overview } }
      projects:
        path: /projects
        title: Projects
        layout: app_shell
        content: { view: project_table }
        actions:
          new_project: { kind: form, form: new_project, label: New project, icon: plus }
      project_detail:
        path: /projects/{id}
        title: Project
        entity: Project
        content: { view: project_detail }
        actions:
          delete:
            kind: operation
            operation: delete_project
            variant: destructive
            confirm: { title: "Delete the project?", confirm_label: Delete }
            on_success: { toast: Project deleted, navigate: projects }
      project_tasks:
        path: /projects/{project_id}/tasks
        title: Tasks
        breadcrumb: All tasks
        content: { custom: true }
      settings: { path: /settings, title: Settings, content: { custom: true } }
    ui:
      theme: { default_mode: dark, mode_toggle: false }
      layouts:
        app_shell:
          sidebar:
            navigation: main
            title: Demo
            icon: folder-kanban
            width: "{size.sidebar}"
            mode: icons
          topbar:
            breadcrumbs: true
            search: true
            actions:
              help: { kind: navigate, page: settings, icon: circle-help, variant: ghost }
          content: { max_width: "{size.content}", padding: "{spacing.6}" }
          footer: { text: Demo app }
        bare: {}
      navigation:
        main:
          items:
            dashboard: { page: dashboard, icon: layout-dashboard }
          groups:
            workspace:
              label: Workspace
              collapsible: true
              items:
                projects:
                  page: projects
                  label: All projects
                  icon: folder-kanban
                  items:
                    tasks: { page: project_tasks, icon: list-checks }
      defaults: { layout: app_shell }
    """
)


def load(text: str = VALID) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def errors(text: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(text)
    return caught.value.diagnostics


def test_loads_the_theme_and_the_defaults() -> None:
    ui = load().ui

    assert ui is not None
    assert ui.theme is not None
    assert ui.theme.default_mode == "dark"
    assert ui.theme.mode_toggle is False
    assert ui.defaults is not None
    assert ui.defaults.layout == "app_shell"


def test_loads_a_layout_with_its_regions() -> None:
    ui = load().ui
    assert ui is not None

    layout = ui.layouts["app_shell"]

    assert isinstance(layout, Layout)
    assert layout.sidebar is not None
    assert layout.sidebar.navigation == "main"
    assert layout.sidebar.width == "{size.sidebar}"
    assert layout.sidebar.mode == "icons"
    assert layout.sidebar.side == "left"
    assert layout.topbar is not None
    assert layout.topbar.search is True
    assert isinstance(layout.topbar.actions["help"], NavigateAction)
    assert layout.content is not None
    assert layout.content.padding == "{spacing.6}"
    assert layout.footer is not None
    assert layout.footer.text == "Demo app"


def test_regions_are_optional() -> None:
    ui = load().ui
    assert ui is not None

    layout = ui.layouts["bare"]

    assert (layout.sidebar, layout.topbar, layout.content, layout.footer) == (
        None,
        None,
        None,
        None,
    )


def test_loads_the_navigation() -> None:
    ui = load().ui
    assert ui is not None

    menu = ui.navigation["main"]

    assert isinstance(menu, Menu)
    assert list(menu.items) == ["dashboard"]
    group = menu.groups["workspace"]
    assert isinstance(group, MenuGroup)
    assert group.label == "Workspace"
    assert group.collapsible is True
    item = group.items["projects"]
    assert isinstance(item, MenuItem)
    assert (item.page, item.label, item.icon) == ("projects", "All projects", "folder-kanban")
    assert item.items["tasks"].page == "project_tasks"


def test_navigation_elements_have_ids() -> None:
    definition = load()

    assert definition.find("ui.navigation.main.groups.workspace.items.projects") is not None
    assert definition.find("ui.navigation.main.groups.workspace.items.projects.items.tasks")
    assert definition.find("ui.navigation.main.items.dashboard") is not None
    assert definition.find("ui.layouts.app_shell.sidebar") is not None
    assert definition.find("pages.project_detail.actions.delete") is not None


def test_pages_declare_their_layout_content_and_actions() -> None:
    pages = load().pages

    assert pages["projects"].layout == "app_shell"
    assert pages["dashboard"].layout is None
    assert pages["projects"].content is not None
    assert pages["projects"].content.view == "project_table"
    assert pages["settings"].content is not None
    assert pages["settings"].content.custom is True
    action = pages["projects"].actions["new_project"]
    assert isinstance(action, FormAction)
    assert action.form == "new_project"
    delete = pages["project_detail"].actions["delete"]
    assert isinstance(delete, OperationAction)
    assert delete.variant == "destructive"
    assert delete.confirm is not None
    assert delete.confirm.title == "Delete the project?"
    assert delete.on_success is not None
    assert delete.on_success.navigate == "projects"


def test_page_parent_is_the_longest_path_prefix() -> None:
    pages = load().pages

    assert page_parent(pages, "dashboard") is None
    assert page_parent(pages, "projects") == "dashboard"
    assert page_parent(pages, "project_detail") == "projects"
    assert page_parent(pages, "project_tasks") == "project_detail"


def test_breadcrumbs_come_from_the_route_structure() -> None:
    pages = load().pages

    assert breadcrumbs(pages, "project_tasks") == [
        Breadcrumb("dashboard", "Dashboard", from_record=False),
        Breadcrumb("projects", "Projects", from_record=False),
        Breadcrumb("project_detail", "Project", from_record=True),
        Breadcrumb("project_tasks", "All tasks", from_record=False),
    ]


def test_page_content_needs_exactly_one_key() -> None:
    [diagnostic] = errors(VALID.replace("{ view: project_table }", "{ view: a, form: b }"))

    assert diagnostic.code == "invalid-value"
    assert diagnostic.message.startswith("Set exactly one of the keys view, form, dashboard")
    assert diagnostic.element_id == "pages.projects.content"


def test_unknown_action_kind_gets_a_hint() -> None:
    [diagnostic] = errors(VALID.replace("kind: operation", "kind: operaton"))

    assert diagnostic.code == "invalid-value"
    assert diagnostic.message == (
        "The kind 'operaton' is not valid. Expected 'navigate', 'form', 'operation', 'custom'."
    )
    assert diagnostic.hint == "Did you mean 'operation'?"
    assert diagnostic.location == Location("app.yaml", 26, 15)


def test_action_needs_a_kind() -> None:
    [diagnostic] = errors(VALID.replace("{ kind: form, form: new_project,", "{ form: new_project,"))

    assert diagnostic.code == "missing-key"
    assert diagnostic.message == "The key 'kind' is missing."


def test_action_keys_depend_on_the_kind() -> None:
    diagnostics = errors(VALID.replace("kind: form, form: new_project", "kind: form, page: x"))

    assert [(d.code, d.message, d.hint) for d in diagnostics] == [
        ("missing-key", "The key 'form' is missing.", None),
        ("unknown-key", "The key 'page' is not known here.", None),
    ]


def test_sub_items_cannot_have_items() -> None:
    text = VALID.replace(
        "tasks: { page: project_tasks, icon: list-checks }",
        "tasks: { page: project_tasks, items: {} }",
    )

    [diagnostic] = errors(text)

    assert diagnostic.code == "unknown-key"


def test_invalid_icon_name() -> None:
    [diagnostic] = errors(VALID.replace("icon: list-checks", "icon: ListChecks"))

    assert diagnostic.code == "invalid-value"
    assert "does not match the pattern" in diagnostic.message


def test_style_values_must_be_token_references() -> None:
    [diagnostic] = errors(VALID.replace('width: "{size.sidebar}"', "width: 16rem"))

    assert diagnostic.code == "invalid-value"
    assert diagnostic.element_id == "ui.layouts.app_shell.sidebar"


def test_invalid_sidebar_mode() -> None:
    [diagnostic] = errors(VALID.replace("mode: icons", "mode: icon"))

    assert diagnostic.hint == "Did you mean 'icons'?"
