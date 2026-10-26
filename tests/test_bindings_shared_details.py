"""Tests of the detail view and dashboard values of the front-end bindings.

The modules are `appgen.bindings.shared.details` and
`appgen.bindings.shared.dashboards`.
"""

from pathlib import Path

import pytest

from appgen.bindings.shared.dashboards import span_classes
from appgen.bindings.shared.details import related_test, section_grid
from appgen.bindings.shared.views import ViewContext
from appgen.dsl import load_definition
from appgen.dsl.ui.common import Grid, GridOverride

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"
DETAILS = Path(__file__).parent / "fixtures" / "ui-details.yaml"


@pytest.fixture(scope="module")
def example() -> ViewContext:
    return ViewContext(load_definition(EXAMPLE))


@pytest.fixture(scope="module")
def details() -> ViewContext:
    return ViewContext(load_definition(DETAILS))


def test_a_section_grid_has_one_column_on_small_screens() -> None:
    assert section_grid(1) == "grid gap-x-6 gap-y-4"
    assert section_grid(2) == "grid gap-x-6 gap-y-4 sm:grid-cols-2"
    assert section_grid(4) == "grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4"


def test_a_relation_tab_tests_the_related_records(example: ViewContext) -> None:
    assert related_test(example, "Project", "tasks") == "row.projectId === record.id"
    assert related_test(example, "Project", "members") == "record.members.includes(row.id)"


def test_a_detail_view_has_a_header_sections_tabs_and_actions(example: ViewContext) -> None:
    plan = example.detail_plan("task_detail")
    assert plan.title == '{String(record.title ?? "")}'
    assert plan.subtitle == (
        '<FormattedValue value={String(lookups.project.get(record.projectId ?? "")?.name ?? "")} />'
    )
    assert plan.badges == [
        "<BadgeValue set={badges.taskStatus} value={record.status} />",
        "<BadgeValue set={badges.taskPriority} value={record.priority} />",
    ]
    assert plan.lookups == ["Person", "Project"]
    summary = plan.sections[0]
    assert summary.grid == "grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4"
    assert [label for label, _ in summary.fields] == [
        "Assignee",
        "Due date",
        "Estimate hours",
        "Completed at",
    ]
    tabs = {tab.name: tab for tab in plan.tabs}
    assert tabs["comments"].view == "comment_table"
    assert tabs["comments"].where == "row.taskId === record.id"
    activity = tabs["activity"].gap
    assert activity is not None
    assert activity.name == "ActivityTab"
    assert (
        'import { ActivityTab } from "@/widgets/task-detail/ui/activity-tab.gen";' in plan.imports
    )
    # Form actions come with the forms.
    assert [a.name for a in plan.actions] == ["complete"]
    assert plan.states is not None
    assert plan.states.empty is not None
    assert plan.states.empty.title == "Nothing here yet"


def test_a_detail_view_without_a_header_shows_the_display_field(details: ViewContext) -> None:
    plan = details.detail_plan("team_detail")
    assert plan.title == '{String(record.name ?? "")}'
    assert plan.lookups == []
    notes = plan.sections[0]
    assert notes.gap is not None
    assert notes.gap.name == "NotesSection"
    assert plan.tabs[0].label == "People"
    assert plan.tabs[0].where == "row.teamId === record.id"


def test_the_span_of_a_widget_fits_the_responsive_columns() -> None:
    grid = Grid(
        columns=4, responsive={"lg": GridOverride(columns=2), "sm": GridOverride(columns=1)}
    )
    assert span_classes(grid, 1) == "col-span-1"
    assert span_classes(grid, 3) == "col-span-3 max-lg:col-span-2 max-sm:col-span-1"
    assert span_classes(Grid(columns=2), 4) == "col-span-2"
    assert span_classes(None, 2) == "col-span-2 max-sm:col-span-1"


def test_a_stat_widget_filters_and_aggregates_the_records(example: ViewContext) -> None:
    plan = example.dashboard_plan("overview")
    widgets = {w.name: w for w in plan.widgets}
    overdue = widgets["overdue_tasks"]
    assert overdue.body == [
        "const rows = data.records.task.filter((row) => "
        'matchesOp(row.dueDate, "lt", today()) && matchesOp(row.status, "ne", "done"));',
        "return rows.length;",
    ]
    assert overdue.href == 'pageHref("taskBoard")'
    assert overdue.color == "var(--destructive)"
    budget = widgets["total_budget"]
    assert budget.body[-1] == 'return aggregate(rows.map((row) => row.budget), "sum");'
    assert budget.format == "currency"
    assert plan.entities == ["Person", "Project", "Task"]


def test_a_chart_widget_groups_the_records(example: ViewContext, details: ViewContext) -> None:
    widgets = {w.name: w for w in example.dashboard_plan("overview").widgets}
    status = widgets["tasks_by_status"]
    assert status.chart == "donut"
    assert '{ key: "todo", label: "To do", color: "var(--status-neutral)" }' in status.body[-1]
    hours = widgets["hours_by_person"]
    assert "(row) => row.assigneeId ?? null" in hours.body[-1]
    assert 'aggregate(group.map((row) => row.estimateHours), "sum") ?? 0' in hours.body[-1]
    assert hours.value_label == "Estimate hours"
    other = {w.name: w for w in details.dashboard_plan("stats").widgets}
    assert other["by_month"].body[-1] == (
        'return intervalRows(rows, (row) => row.received, (group) => group.length, "month");'
    )
    assert other["by_month"].value_label == "Items"
    assert '{ key: "new", label: "New" }' in other["by_stage"].body[-1]


def test_a_filter_of_a_list_or_now_or_a_path(details: ViewContext) -> None:
    widgets = {w.name: w for w in details.dashboard_plan("stats").widgets}
    assert widgets["average"].body[0] == (
        "const rows = data.records.item.filter((row) => "
        'matchesOp(row.updatedAt, "lte", new Date().toISOString()) && '
        'matchesOp(row.stage, "in", ["open", "closed"]));'
    )
    assert 'matchesOp((row.tags ?? []), "ne", null)' in widgets["tagged"].body[0]
    assert (
        'matchesOp(lookups.team.get(lookups.member.get(row.ownerId ?? "")?.teamId ?? "")'
        '?.name, "eq", "Core")'
    ) in widgets["tagged"].body[0]


def test_a_list_widget_shows_the_columns_or_the_cards_of_its_view(
    example: ViewContext, details: ViewContext
) -> None:
    widgets = {w.name: w for w in example.dashboard_plan("overview").widgets}
    due = widgets["due_soon"]
    assert [c.name for c in due.columns] == [
        "title",
        "status",
        "priority",
        "assignee",
        "due_date",
        "screenshot",
    ]
    assert due.body[-1] == "return sortBy(rows, (row) => row.dueDate).slice(0, 6);"
    assert due.sort_id == "ui.dashboards.overview.widgets.due_soon.sort"
    people = {w.name: w for w in details.dashboard_plan("stats").widgets}["people"]
    assert people.card is not None
    assert people.columns == []
    assert people.body[-1] == "return sortBy(rows, (row) => row.id).slice(0, 3);"


def test_the_runtime_parts_include_the_details_and_the_dashboards(details: ViewContext) -> None:
    assert details.runtime
    assert {"detail", "dashboard", "chart", "formatted", "avatar"} <= details.features


def test_the_form_actions_of_a_detail_view_open_the_forms() -> None:
    plan = ViewContext(load_definition(EXAMPLE), forms=True).detail_plan("task_detail")
    assert [a.name for a in plan.actions] == ["edit", "assign", "complete"]
    assert [f.name for f in plan.forms] == ["edit_task", "assign_task"]
