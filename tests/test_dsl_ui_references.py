from textwrap import dedent

import pytest
from ui_support import UI_TOKENS

from appgen.dsl import AppDefinition, load_definition_text
from appgen.dsl.validator import validate_definition

VALID = (
    dedent(
        """\
        version: 0
        app: { name: demo, title: Demo }
        entities:
          Task:
            display_field: title
            fields:
              title: { type: string }
              status: { type: enum, values: [todo, done] }
        operations:
          create_task: { kind: create, entity: Task }
          update_task: { kind: update, entity: Task }
          delete_task: { kind: delete, entity: Task }
          move_task:
            kind: custom
            entity: Task
            params:
              status: { type: enum, values: [todo, done] }
        pages:
          home: { path: /, title: Home, layout: shell, content: { dashboard: overview } }
          tasks:
            path: /tasks
            title: Tasks
            content: { view: task_table }
            actions:
              new: { kind: form, form: new_task }
          task:
            path: "/tasks/{id}"
            title: Task
            entity: Task
            content: { view: task_detail }
            actions:
              delete:
                kind: operation
                operation: delete_task
                on_success: { navigate: tasks }
          board: { path: /board, title: Board, content: { view: task_board } }
          new_task: { path: /tasks/new, title: New task, content: { form: new_task } }
        ui:
          layouts:
            shell:
              sidebar: { navigation: main, width: "{size.sidebar}" }
              content: { max_width: "{size.content}", padding: "{spacing.6}" }
              responsive:
                md: { sidebar: { mode: drawer } }
          navigation:
            main:
              items:
                home: { page: home, icon: house }
                tasks: { page: tasks, icon: list }
          badges:
            status:
              field: Task.status
              values: { done: { color: "{color.blue}" } }
          views:
            task_table:
              kind: table
              entity: Task
              columns:
                title: { link: task, width: "{size.col_lg}", hide_below: sm }
                status: { badge: status }
              row_actions:
                open: { kind: navigate, page: task, params: { id: id } }
                edit: { kind: form, form: edit_task }
            task_board:
              kind: board
              entity: Task
              group_by: status
              columns: { todo: { color: "{color.slate}" } }
              move: move_task
            task_detail:
              kind: detail
              entity: Task
              sections: { main: { fields: [title, status] } }
          forms:
            new_task:
              entity: Task
              operation: create_task
              fields: { title: {} }
              grid: { columns: 2, gap: "{spacing.4}", responsive: { sm: { columns: 1 } } }
              on_success: { navigate: tasks }
            edit_task: { entity: Task, operation: update_task, fields: { title: {} } }
          dashboards:
            overview:
              grid: { columns: 2, gap: "{spacing.6}" }
              widgets:
                open:
                  kind: stat
                  entity: Task
                  filter: { status: todo }
                  color: "{color.primary}"
                  link: tasks
          defaults: { layout: shell }
        """
    )
    + UI_TOKENS
)


def load(text: str) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def problems(text: str) -> list[tuple[str, str | None, str]]:
    return [(d.code, d.element_id, d.message) for d in validate_definition(load(text))]


def test_valid_references_have_no_problems() -> None:
    assert problems(VALID) == []


@pytest.mark.parametrize(
    ("old", "new", "element_id", "message"),
    [
        (
            "layout: shell, content",
            "layout: shel, content",
            "pages.home",
            "The layout 'shel' does not exist.",
        ),
        (
            "defaults: { layout: shell }",
            "defaults: { layout: app }",
            "ui.defaults",
            "The layout 'app' does not exist.",
        ),
        (
            "{ dashboard: overview }",
            "{ dashboard: overvew }",
            "pages.home.content",
            "The dashboard 'overvew' does not exist.",
        ),
        (
            "{ view: task_table }",
            "{ view: task_tabel }",
            "pages.tasks.content",
            "The view 'task_tabel' does not exist.",
        ),
        (
            "content: { form: new_task }",
            "content: { form: new_tsk }",
            "pages.new_task.content",
            "The form 'new_tsk' does not exist.",
        ),
        (
            "{ kind: form, form: new_task }",
            "{ kind: form, form: new }",
            "pages.tasks.actions.new",
            "The form 'new' does not exist.",
        ),
        (
            "operation: delete_task",
            "operation: remove_task",
            "pages.task.actions.delete",
            "The operation 'remove_task' does not exist.",
        ),
        (
            "on_success: { navigate: tasks }\n  board",
            "on_success: { navigate: task_list }\n  board",
            "pages.task.actions.delete.on_success",
            "The page 'task_list' does not exist.",
        ),
        (
            "navigation: main,",
            "navigation: side,",
            "ui.layouts.shell.sidebar",
            "The menu 'side' does not exist.",
        ),
        (
            "home: { page: home, icon: house }",
            "home: { page: start, icon: house }",
            "ui.navigation.main.items.home",
            "The page 'start' does not exist.",
        ),
        (
            "{ link: task,",
            "{ link: task_page,",
            "ui.views.task_table.columns.title",
            "The page 'task_page' does not exist.",
        ),
        (
            "params: { id: id }",
            "params: { key: id }",
            "ui.views.task_table.row_actions.open",
            "The path parameter 'key' does not exist.",
        ),
        (
            "form: edit_task }",
            "form: edit }",
            "ui.views.task_table.row_actions.edit",
            "The form 'edit' does not exist.",
        ),
        (
            "on_success: { navigate: tasks }\n    edit_task",
            "on_success: { navigate: list }\n    edit_task",
            "ui.forms.new_task.on_success",
            "The page 'list' does not exist.",
        ),
        (
            "link: tasks\n",
            "link: all_tasks\n",
            "ui.dashboards.overview.widgets.open",
            "The page 'all_tasks' does not exist.",
        ),
        (
            "move: move_task",
            "move: shift_task",
            "ui.views.task_board",
            "The operation 'shift_task' does not exist.",
        ),
        (
            'width: "{size.sidebar}"',
            'width: "{size.side}"',
            "ui.layouts.shell.sidebar",
            "The token 'size.side' does not exist.",
        ),
        (
            'color: "{color.blue}"',
            'color: "{color.red}"',
            "ui.badges.status.values.done",
            "The token 'color.red' does not exist.",
        ),
        (
            'gap: "{spacing.4}"',
            'gap: "{spacing.5}"',
            "ui.forms.new_task.grid",
            "The token 'spacing.5' does not exist.",
        ),
        (
            "md: { sidebar",
            "xl: { sidebar",
            "ui.layouts.shell",
            "The breakpoint token 'xl' does not exist.",
        ),
        (
            "hide_below: sm",
            "hide_below: xs",
            "ui.views.task_table.columns.title",
            "The breakpoint token 'xs' does not exist.",
        ),
        (
            "responsive: { sm: { columns: 1 } }",
            "responsive: { tablet: { columns: 1 } }",
            "ui.forms.new_task.grid",
            "The breakpoint token 'tablet' does not exist.",
        ),
    ],
)
def test_missing_references(old: str, new: str, element_id: str, message: str) -> None:
    assert old in VALID

    assert problems(VALID.replace(old, new, 1)) == [("unknown-reference", element_id, message)]


@pytest.mark.parametrize(
    ("old", "new", "code", "element_id"),
    [
        (
            'width: "{size.sidebar}"',
            'width: "{spacing.6}"',
            "unsuitable-token",
            "ui.layouts.shell.sidebar",
        ),
        (
            'padding: "{spacing.6}"',
            'padding: "{color.blue}"',
            "unsuitable-token",
            "ui.layouts.shell.content",
        ),
        (
            'color: "{color.primary}"',
            'color: "{size.content}"',
            "unsuitable-token",
            "ui.dashboards.overview.widgets.open",
        ),
        ("move: move_task", "move: delete_task", "unsuitable-operation", "ui.views.task_board"),
    ],
)
def test_unsuitable_references(old: str, new: str, code: str, element_id: str) -> None:
    assert old in VALID

    found = [(c, e) for c, e, _ in problems(VALID.replace(old, new, 1))]

    assert found == [(code, element_id)]


def test_custom_move_operation_needs_the_group_parameter() -> None:
    old = "params:\n      status: { type: enum, values: [todo, done] }"
    assert old in VALID
    text = VALID.replace(old, "params:\n      note: { type: text }")

    assert [(c, e) for c, e, _ in problems(text)] == [
        ("unsuitable-operation", "ui.views.task_board")
    ]


def test_detail_view_needs_a_path_parameter() -> None:
    text = VALID.replace('path: "/tasks/{id}"', "path: /tasks/all")

    assert [(c, e) for c, e, _ in problems(text)] == [
        ("unsuitable-view", "pages.task.content"),
        ("unknown-reference", "ui.views.task_table.row_actions.open"),
    ]


def test_view_entity_must_match_the_page_entity() -> None:
    text = VALID.replace(
        "entities:\n",
        "entities:\n  Note:\n    fields:\n      text: { type: string }\n",
        1,
    ).replace(
        "entity: Task\n    content: { view: task_detail }",
        "entity: Note\n    content: { view: task_detail }",
    )

    assert [(c, e) for c, e, _ in problems(text)] == [("unsuitable-view", "pages.task.content")]


def test_missing_reference_gets_a_hint() -> None:
    [diagnostic] = validate_definition(
        load(VALID.replace("{ view: task_table }", "{ view: task_tabel }"))
    )

    assert diagnostic.hint == "Did you mean 'task_table'?"
