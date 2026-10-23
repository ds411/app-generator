from textwrap import dedent

import pytest

from appgen.dsl import AppDefinition, DefinitionError, Diagnostic, load_definition_text
from appgen.dsl.ui.dashboards import ChartWidget, CustomWidget, ListWidget, StatWidget
from appgen.dsl.ui.views import DetailView
from appgen.dsl.validator import validate_definition

VALID = dedent(
    """\
    version: 0
    app: { name: demo, title: Demo }
    entities:
      Person:
        display_field: name
        fields:
          name: { type: string }
      Project:
        display_field: name
        fields:
          name: { type: string }
          status: { type: enum, values: [planned, active, done] }
          budget: { type: decimal }
        relations:
          owner: { kind: many_to_one, target: Person }
          tasks: { kind: one_to_many, target: Task, inverse: project }
          members: { kind: many_to_many, target: Person }
      Task:
        display_field: title
        fields:
          title: { type: string }
          status: { type: enum, values: [todo, in_progress, done] }
          due_date: { type: date }
          estimate: { type: decimal }
        relations:
          project: { kind: many_to_one, target: Project, inverse: tasks }
          assignee: { kind: many_to_one, target: Person }
    ui:
      badges:
        task_status: { field: Task.status, values: { done: { icon: check } } }
      views:
        task_table:
          kind: table
          entity: Task
          columns: { title: {}, status: {}, due_date: {} }
        person_cards:
          kind: cards
          entity: Person
        task_detail:
          kind: detail
          entity: Task
          title: Task
          header: { title: title, subtitle: project, badges: [status] }
          sections:
            summary: { title: Summary, fields: [status, due_date, estimate], columns: 3 }
          tabs:
            details:
              label: Details
              icon: info
              sections:
                people: { title: People, fields: [assignee, project.owner] }
                notes: { title: Notes, custom: true }
            activity: { label: Activity, custom: true }
          actions:
            edit: { kind: form, form: edit_task }
        project_detail:
          kind: detail
          entity: Project
          tabs:
            tasks: { label: Tasks, relation: tasks, view: task_table }
            members: { label: Members, relation: members, view: person_cards }
      dashboards:
        overview:
          title: Overview
          description: The state of all projects.
          grid: { columns: 4, gap: "{spacing.6}" }
          widgets:
            active_projects:
              kind: stat
              label: Active projects
              entity: Project
              filter: { status: active }
              icon: folder-kanban
              color: "{color.primary}"
              link: projects
            overdue_tasks:
              kind: stat
              label: Overdue tasks
              entity: Task
              aggregate: count
              filter: { due_date: { lt: $today }, status: { ne: done } }
              icon: alarm-clock
            total_budget:
              kind: stat
              label: Budget
              entity: Project
              aggregate: sum
              field: budget
              format: currency
            open_estimate:
              kind: stat
              entity: Task
              aggregate: avg
              field: estimate
              filter: { status: { in: [todo, in_progress] } }
            tasks_by_status:
              kind: chart
              label: Tasks by status
              chart: donut
              entity: Task
              group_by: status
              badge: task_status
              span: 2
            tasks_by_owner:
              kind: chart
              chart: bar
              entity: Task
              group_by: project.owner
              aggregate: sum
              field: estimate
              span: 2
            due_soon:
              kind: list
              label: Due soon
              view: task_table
              filter: { status: { not_in: [done] } }
              sort: { field: due_date }
              limit: 8
              link: tasks
              span: 3
            team: { kind: custom, label: Team, span: 1 }
    """
)


def load(text: str = VALID) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def codes(text: str) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in validate_definition(load(text))]


def errors(text: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(text)
    return caught.value.diagnostics


def test_valid_detail_views_and_dashboards_have_no_problems() -> None:
    assert codes(VALID) == []


def test_loads_a_detail_view() -> None:
    ui = load().ui
    assert ui is not None

    view = ui.views["task_detail"]

    assert isinstance(view, DetailView)
    assert view.header is not None
    assert view.header.badges == ["status"]
    assert view.sections["summary"].columns == 3
    details = view.tabs["details"]
    assert details.icon == "info"
    assert details.sections["notes"].custom is True
    assert view.tabs["activity"].custom is True
    tasks = ui.views["project_detail"]
    assert isinstance(tasks, DetailView)
    assert (tasks.tabs["tasks"].relation, tasks.tabs["tasks"].view) == ("tasks", "task_table")


def test_loads_a_dashboard() -> None:
    ui = load().ui
    assert ui is not None

    dashboard = ui.dashboards["overview"]

    assert dashboard.grid is not None
    assert dashboard.grid.columns == 4
    widgets = dashboard.widgets
    active = widgets["active_projects"]
    assert isinstance(active, StatWidget)
    assert (active.aggregate, active.filter, active.link) == (
        "count",
        {"status": "active"},
        "projects",
    )
    assert isinstance(widgets["total_budget"], StatWidget)
    assert widgets["total_budget"].format == "currency"
    chart = widgets["tasks_by_status"]
    assert isinstance(chart, ChartWidget)
    assert (chart.chart, chart.group_by, chart.span) == ("donut", "status", 2)
    due = widgets["due_soon"]
    assert isinstance(due, ListWidget)
    assert due.limit == 8
    assert isinstance(widgets["team"], CustomWidget)


def test_dashboard_elements_have_ids() -> None:
    definition = load()

    assert definition.find("ui.dashboards.overview.widgets.overdue_tasks") is not None
    assert definition.find("ui.views.task_detail.tabs.details.sections.people") is not None
    assert definition.find("ui.views.task_detail.sections.summary") is not None


@pytest.mark.parametrize(
    ("old", "new", "code", "element_id"),
    [
        (
            "subtitle: project,",
            "subtitle: projet,",
            "unknown-reference",
            "ui.views.task_detail.header",
        ),
        ("badges: [status]", "badges: [title]", "unsuitable-field", "ui.views.task_detail.header"),
        (
            "fields: [status, due_date, estimate]",
            "fields: [status, due]",
            "unknown-reference",
            "ui.views.task_detail.sections.summary",
        ),
        (
            "project.owner]",
            "project.lead]",
            "unknown-reference",
            "ui.views.task_detail.tabs.details.sections.people",
        ),
        (
            "relation: tasks,",
            "relation: task,",
            "unknown-reference",
            "ui.views.project_detail.tabs.tasks",
        ),
        (
            "relation: tasks,",
            "relation: owner,",
            "unsuitable-field",
            "ui.views.project_detail.tabs.tasks",
        ),
        (
            "view: task_table }",
            "view: task_tabel }",
            "unknown-reference",
            "ui.views.project_detail.tabs.tasks",
        ),
        (
            "view: person_cards }",
            "view: task_table }",
            "unsuitable-view",
            "ui.views.project_detail.tabs.members",
        ),
        (
            "view: person_cards }",
            "view: task_detail }",
            "unsuitable-view",
            "ui.views.project_detail.tabs.members",
        ),
        (
            "entity: Project\n          filter: { status: active }",
            "entity: Projects\n          filter: { status: active }",
            "unknown-reference",
            "ui.dashboards.overview.widgets.active_projects",
        ),
        (
            "filter: { status: active }",
            "filter: { state: active }",
            "unknown-reference",
            "ui.dashboards.overview.widgets.active_projects",
        ),
        (
            "filter: { status: active }",
            "filter: { status: activ }",
            "unknown-reference",
            "ui.dashboards.overview.widgets.active_projects",
        ),
        (
            "lt: $today",
            "lt: $tomorrow",
            "invalid-value",
            "ui.dashboards.overview.widgets.overdue_tasks",
        ),
        (
            "status: { ne: done }",
            "status: { neq: done }",
            "unknown-reference",
            "ui.dashboards.overview.widgets.overdue_tasks",
        ),
        (
            "aggregate: count\n",
            "aggregate: count\n          field: estimate\n",
            "invalid-value",
            "ui.dashboards.overview.widgets.overdue_tasks",
        ),
        (
            "field: budget",
            "field: name",
            "unsuitable-field",
            "ui.dashboards.overview.widgets.total_budget",
        ),
        (
            "aggregate: avg\n          field: estimate\n",
            "aggregate: avg\n",
            "missing-key",
            "ui.dashboards.overview.widgets.open_estimate",
        ),
        (
            "in: [todo, in_progress]",
            "in: [todo, doing]",
            "unknown-reference",
            "ui.dashboards.overview.widgets.open_estimate",
        ),
        (
            "group_by: status",
            "group_by: title",
            "unsuitable-field",
            "ui.dashboards.overview.widgets.tasks_by_status",
        ),
        (
            "badge: task_status",
            "badge: project_status",
            "unknown-reference",
            "ui.dashboards.overview.widgets.tasks_by_status",
        ),
        (
            "group_by: project.owner",
            "group_by: project.boss",
            "unknown-reference",
            "ui.dashboards.overview.widgets.tasks_by_owner",
        ),
        (
            "view: task_table\n          filter",
            "view: task_detail\n          filter",
            "unsuitable-view",
            "ui.dashboards.overview.widgets.due_soon",
        ),
        (
            "sort: { field: due_date }",
            "sort: { field: due }",
            "unknown-reference",
            "ui.dashboards.overview.widgets.due_soon.sort",
        ),
    ],
)
def test_problems(old: str, new: str, code: str, element_id: str) -> None:
    assert old in VALID

    assert codes(VALID.replace(old, new, 1)) == [(code, element_id)]


def test_tab_needs_one_kind_of_content() -> None:
    [diagnostic] = errors(VALID.replace("{ label: Activity, custom: true }", "{ label: Activity }"))

    assert diagnostic.message.startswith("Set exactly one of: sections, relation and view")
    assert diagnostic.element_id == "ui.views.task_detail.tabs.activity"


def test_related_tab_needs_a_view() -> None:
    [diagnostic] = errors(VALID.replace("relation: tasks, view: task_table", "relation: tasks"))

    assert diagnostic.message.startswith("Set both relation and view")


def test_dashboard_needs_widgets() -> None:
    text = VALID[: VALID.index("      widgets:")] + "      widgets: {}\n"

    [diagnostic] = errors(text)

    assert diagnostic.message == "Expected one or more items."


def test_unknown_widget_kind() -> None:
    [diagnostic] = errors(VALID.replace("kind: custom, label: Team", "kind: map, label: Team"))

    assert (
        diagnostic.message
        == "The kind 'map' is not valid. Expected 'stat', 'chart', 'list', 'custom'."
    )
