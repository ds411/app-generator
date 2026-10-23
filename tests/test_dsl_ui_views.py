from textwrap import dedent

import pytest
from ui_support import UI_TOKENS

from appgen.dsl import AppDefinition, DefinitionError, Diagnostic, load_definition_text
from appgen.dsl.ui.views import (
    BoardView,
    CardsView,
    DateRangeFilter,
    SearchFilter,
    SelectFilter,
    TableView,
)
from appgen.dsl.validator import validate_definition

VALID = (
    dedent(
        """\
    version: 0
    app: { name: demo, title: Demo }
    entities:
      Person:
        display_field: name
        fields:
          name: { type: string }
          email: { type: email }
      Project:
        display_field: name
        fields:
          name: { type: string }
          status: { type: enum, values: [planned, active, done] }
          due_date: { type: date }
          budget: { type: decimal }
          archived: { type: boolean }
        relations:
          owner: { kind: many_to_one, target: Person }
          tasks: { kind: one_to_many, target: Task, inverse: project }
      Task:
        display_field: title
        fields:
          title: { type: string }
          status: { type: enum, values: [todo, in_progress, done] }
          due_date: { type: date }
        relations:
          project: { kind: many_to_one, target: Project, inverse: tasks }
          assignee: { kind: many_to_one, target: Person }
    operations:
      update_task: { kind: update, entity: Task }
      delete_project: { kind: delete, entity: Project }
    ui:
      badges:
        project_status:
          field: Project.status
          values:
            planned: { label: Planned, color: "{color.slate}", icon: circle-dashed }
            active: { label: Active, color: "{color.blue}" }
        task_status:
          field: Task.status
          values:
            done: { icon: circle-check }
      views:
        project_table:
          kind: table
          entity: Project
          title: Projects
          columns:
            name: { label: Name, link: project_detail, width: "{size.col_lg}" }
            status: { format: badge, badge: project_status }
            owner: { format: avatar, label: Owner }
            owner_email: { field: owner.email, format: email, sortable: false }
            due_date: { format: date, align: end }
            budget: { format: currency, align: end }
          sort: { field: due_date, direction: desc }
          filters:
            search: { kind: search, fields: [name, owner.name], label: Search }
            status: { kind: select, field: status, multiple: true, default: [active] }
            owner: { kind: select, field: owner }
            archived: { kind: boolean, field: archived, default: false }
            due: { kind: date_range, field: due_date }
          pagination: { page_size: 20, page_sizes: [10, 20, 50] }
          row_actions:
            open: { kind: navigate, page: project_detail }
            delete: { kind: operation, operation: delete_project, variant: destructive }
          row_click: open
          selection: true
          bulk_actions:
            delete: { kind: operation, operation: delete_project }
        project_cards:
          kind: cards
          entity: Project
          card:
            subtitle: owner
            badge: { field: status, badge: project_status }
            fields: [due_date, budget]
            footer: [owner.email]
          grid: { columns: 3, gap: "{spacing.4}" }
        task_board:
          kind: board
          entity: Task
          group_by: status
          columns:
            todo: { label: To do, color: "{color.slate}" }
            in_progress: { label: In progress, limit: 5 }
          card:
            title: title
            subtitle: project
            fields: [assignee, due_date]
          sort: { field: due_date }
          move: update_task
    """
    )
    + UI_TOKENS
    + "pages:\n"
    + '  project_detail: { path: "/projects/{id}", title: Project, entity: Project }\n'
)


def load(text: str = VALID) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def problems(text: str) -> list[tuple[str, str | None, str]]:
    return [(d.code, d.element_id, d.message) for d in validate_definition(load(text))]


def errors(text: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(text)
    return caught.value.diagnostics


def test_valid_views_have_no_problems() -> None:
    assert problems(VALID) == []


def test_loads_a_table_view() -> None:
    ui = load().ui
    assert ui is not None

    view = ui.views["project_table"]

    assert isinstance(view, TableView)
    assert view.entity == "Project"
    assert list(view.columns) == ["name", "status", "owner", "owner_email", "due_date", "budget"]
    assert view.columns["name"].link == "project_detail"
    assert view.columns["name"].width == "{size.col_lg}"
    assert view.columns["owner_email"].field == "owner.email"
    assert view.columns["budget"].align == "end"
    assert view.sort is not None
    assert (view.sort.field, view.sort.direction) == ("due_date", "desc")
    assert isinstance(view.filters["search"], SearchFilter)
    assert view.filters["search"].fields == ["name", "owner.name"]
    status = view.filters["status"]
    assert isinstance(status, SelectFilter)
    assert status.multiple is True
    assert status.default == ["active"]
    assert isinstance(view.filters["due"], DateRangeFilter)
    assert view.pagination is not None
    assert view.pagination.page_sizes == [10, 20, 50]
    assert list(view.row_actions) == ["open", "delete"]
    assert view.row_click == "open"
    assert view.selection is True


def test_loads_a_card_list() -> None:
    ui = load().ui
    assert ui is not None

    view = ui.views["project_cards"]

    assert isinstance(view, CardsView)
    assert view.card is not None
    assert view.card.title is None
    assert view.card.fields == ["due_date", "budget"]
    assert view.card.badge is not None
    assert view.card.badge.badge == "project_status"
    assert view.grid is not None
    assert view.grid.columns == 3


def test_loads_a_board() -> None:
    ui = load().ui
    assert ui is not None

    view = ui.views["task_board"]

    assert isinstance(view, BoardView)
    assert view.group_by == "status"
    assert view.columns["in_progress"].limit == 5
    assert view.move == "update_task"


def test_loads_badge_sets() -> None:
    ui = load().ui
    assert ui is not None

    badge = ui.badges["project_status"]

    assert badge.field == "Project.status"
    assert badge.values["planned"].icon == "circle-dashed"


def test_view_elements_have_ids() -> None:
    definition = load()

    assert definition.find("ui.views.project_table.columns.status") is not None
    assert definition.find("ui.views.project_table.filters.search") is not None
    assert definition.find("ui.views.project_table.row_actions.open") is not None
    assert definition.find("ui.views.task_board.columns.todo") is not None
    assert definition.find("ui.badges.project_status.values.active") is not None


@pytest.mark.parametrize(
    ("old", "new", "element_id", "message"),
    [
        (
            "entity: Project\n      title: Projects",
            "entity: Projet\n      title: Projects",
            "ui.views.project_table",
            "The entity 'Projet' does not exist.",
        ),
        (
            "due_date: { format: date, align: end }",
            "due: { format: date, align: end }",
            "ui.views.project_table.columns.due",
            "The entity 'Project' has no field or relation 'due'.",
        ),
        (
            "field: owner.email, format",
            "field: owner.mail, format",
            "ui.views.project_table.columns.owner_email",
            "The entity 'Person' has no field or relation 'mail'.",
        ),
        (
            "fields: [name, owner.name]",
            "fields: [name, tasks.title]",
            "ui.views.project_table.filters.search",
            "The relation 'Project.tasks' is one_to_many. A field path can only go through "
            "many_to_one and one_to_one relations.",
        ),
        (
            "sort: { field: due_date, direction: desc }",
            "sort: { field: deadline, direction: desc }",
            "ui.views.project_table.sort",
            "The entity 'Project' has no field or relation 'deadline'.",
        ),
        (
            "fields: [due_date, budget]",
            "fields: [due_date, cost]",
            "ui.views.project_cards.card",
            "The entity 'Project' has no field or relation 'cost'.",
        ),
        (
            "fields: [assignee, due_date]",
            "fields: [assignee.nam]",
            "ui.views.task_board.card",
            "The entity 'Person' has no field or relation 'nam'.",
        ),
        (
            "field: Project.status",
            "field: Project.state",
            "ui.badges.project_status",
            "The entity 'Project' has no field or relation 'state'.",
        ),
    ],
)
def test_references_to_missing_entities_and_fields(
    old: str, new: str, element_id: str, message: str
) -> None:
    assert old in VALID

    assert problems(VALID.replace(old, new, 1)) == [("unknown-reference", element_id, message)]


def test_missing_field_gets_a_hint() -> None:
    [diagnostic] = validate_definition(
        load(VALID.replace("due_date: { format: date", "due_dat: { format: date"))
    )

    assert diagnostic.hint == "Did you mean 'due_date'?"


@pytest.mark.parametrize(
    ("old", "new", "element_id"),
    [
        (
            "budget: { format: currency",
            "budget: { format: date",
            "ui.views.project_table.columns.budget",
        ),
        (
            "owner: { format: avatar",
            "owner: { format: number",
            "ui.views.project_table.columns.owner",
        ),
        (
            "name: { label: Name,",
            "name: { format: badge, label: Name,",
            "ui.views.project_table.columns.name",
        ),
        (
            "kind: search, fields: [name,",
            "kind: search, fields: [budget,",
            "ui.views.project_table.filters.search",
        ),
        (
            "kind: boolean, field: archived",
            "kind: boolean, field: name",
            "ui.views.project_table.filters.archived",
        ),
        (
            "kind: date_range, field: due_date",
            "kind: date_range, field: owner",
            "ui.views.project_table.filters.due",
        ),
        (
            "kind: select, field: owner",
            "kind: select, field: budget",
            "ui.views.project_table.filters.owner",
        ),
        ("badge: { field: status,", "badge: { field: name,", "ui.views.project_cards.card.badge"),
        ("group_by: status", "group_by: title", "ui.views.task_board"),
        ("field: Project.status", "field: Project.name", "ui.badges.project_status"),
    ],
)
def test_fields_must_suit_their_use(old: str, new: str, element_id: str) -> None:
    assert old in VALID

    [(code, found_id, _)] = problems(VALID.replace(old, new, 1))

    assert (code, found_id) == ("unsuitable-field", element_id)


def test_badge_set_must_exist() -> None:
    assert problems(VALID.replace("badge: project_status }", "badge: project_state }", 1)) == [
        (
            "unknown-reference",
            "ui.views.project_table.columns.status",
            "The badge set 'project_state' does not exist.",
        )
    ]


def test_badge_set_must_be_for_the_field() -> None:
    [(code, element_id, message)] = problems(
        VALID.replace(
            "badge: { field: status, badge: project_status }",
            "badge: { field: status, badge: task_status }",
        )
    )

    assert (code, element_id) == ("unsuitable-badge", "ui.views.project_cards.card.badge")
    assert (
        message
        == "The badge set 'task_status' is for the field 'Task.status', not for 'Project.status'."
    )


def test_badge_values_must_be_enum_values() -> None:
    assert problems(VALID.replace("active: { label: Active", "activ: { label: Active")) == [
        (
            "unknown-reference",
            "ui.badges.project_status.values.activ",
            "The enum value 'activ' does not exist.",
        )
    ]


def test_board_columns_must_be_enum_values() -> None:
    [(code, element_id, _)] = problems(
        VALID.replace("in_progress: { label: In progress", "doing: { label: In progress")
    )

    assert (code, element_id) == ("unknown-reference", "ui.views.task_board.columns.doing")


def test_row_click_must_be_a_row_action() -> None:
    [(code, element_id, message)] = problems(VALID.replace("row_click: open", "row_click: view"))

    assert (code, element_id, message) == (
        "unknown-reference",
        "ui.views.project_table",
        "The row action 'view' does not exist.",
    )


def test_bulk_actions_need_selection() -> None:
    [(code, element_id, _)] = problems(VALID.replace("selection: true", "selection: false"))

    assert (code, element_id) == ("missing-selection", "ui.views.project_table")


def test_unknown_view_kind_gets_a_hint() -> None:
    [diagnostic] = errors(VALID.replace("kind: cards", "kind: card"))

    assert (
        diagnostic.message
        == "The kind 'card' is not valid. Expected 'table', 'cards', 'board', 'detail'."
    )
    assert diagnostic.hint == "Did you mean 'cards'?"


def test_table_needs_columns() -> None:
    diagnostic = errors(VALID.replace("kind: cards\n", "kind: table\n      columns: {}\n"))[0]

    assert diagnostic.message == "Expected one or more items."
    assert diagnostic.element_id == "ui.views.project_cards"


def test_grid_columns_are_limited() -> None:
    [diagnostic] = errors(VALID.replace("columns: 3,", "columns: 13,"))

    assert diagnostic.code == "invalid-value"
    assert diagnostic.element_id == "ui.views.project_cards.grid"
