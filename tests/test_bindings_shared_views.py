"""Tests of the list view values of the front-end bindings (`appgen.bindings.shared.views`)."""

from pathlib import Path

import pytest

from appgen.bindings.shared.views import (
    ViewContext,
    definition_display,
    grid_classes,
    lookups_param,
)
from appgen.dsl import load_definition, load_definition_text
from appgen.dsl.ui.common import Grid, GridOverride
from appgen.gen.render import GenerationError

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"
VIEWS = Path(__file__).parent / "fixtures" / "react-views.yaml"


@pytest.fixture(scope="module")
def example() -> ViewContext:
    return ViewContext(load_definition(EXAMPLE), forms=True)


@pytest.fixture(scope="module")
def views() -> ViewContext:
    return ViewContext(load_definition(VIEWS))


def test_a_field_path_reads_the_related_records_from_the_lookups(views: ViewContext) -> None:
    value = views.value("Item", "owner.team.lead.name")
    assert value.expr == (
        'lookups.member.get(lookups.team.get(lookups.member.get(row.ownerId ?? "")'
        '?.teamId ?? "")?.leadId ?? "")?.name'
    )
    assert value.kind == "field"
    owner = views.value("Item", "owner")
    assert owner.kind == "one"
    assert owner.key_expr == "row.ownerId ?? null"
    assert owner.text_expr == 'String(lookups.member.get(row.ownerId ?? "")?.name ?? "")'
    tags = views.value("Item", "tags")
    assert tags.kind == "many"
    assert tags.key_expr == "(row.tags ?? [])"
    assert views.view_plan("item_table").lookups == ["Member", "Team"]


def test_an_enum_field_takes_the_badge_set_of_the_field(example: ViewContext) -> None:
    value = example.value("Project", "status")
    assert value.format == "badge"
    assert value.badge == "projectStatus"
    assert example.value("Project", "due_date").format == "date"


def test_the_filters_give_their_state_and_their_match(views: ViewContext) -> None:
    filters = {f.name: f for f in views.view_plan("item_table").filters}
    assert filters["search"].default == '""'
    assert filters["search"].match.startswith("matchesSearch(filters.search, [")
    assert filters["stage"].default == '["new", "open"]'
    assert filters["stage"].state_type == "string[]"
    assert filters["stage"].multiple
    assert filters["kind"].options == (
        '[{ value: "book", label: "Book" }, { value: "tool", label: "Tool" }, '
        '{ value: "part", label: "Part" }]'
    )
    assert filters["tag"].match == (
        "filters.tag === null || (row.tags ?? []).includes(filters.tag)"
    )
    assert filters["owner"].options is not None
    assert filters["owner"].options.startswith("[...lookups.member.values()]")
    assert filters["in_stock"].match == "!filters.inStock || row.inStock === true"
    assert filters["received"].match == "inDateRange(row.received, filters.received)"


def test_the_actions_give_their_paths_and_their_code(views: ViewContext) -> None:
    plan = views.view_plan("item_table")
    rows = {a.name: a for a in plan.row_actions}
    assert rows["open"].href == 'pageHref("item", { id: String(record.id) })'
    team = rows["team"].href
    assert team is not None
    assert 'team: String(lookups.member.get(record.ownerId ?? "")?.teamId ?? null)' in team
    assert rows["delete"].run == "Promise.all(records.map((record) => deleteItem(record.id)))"
    assert rows["delete"].navigate_to == 'pageHref("items")'
    assert rows["restock"].imports == ('import { restock } from "@/features/restock";',)
    assert rows["flag"].run is not None
    assert rows["flag"].run.startswith("Promise.all(records.map((record) => ")
    bulk = {a.name: a for a in plan.bulk_actions}
    assert bulk["export"].run is not None
    assert bulk["export"].run.endswith("(records)")
    assert [a.name for a in plan.actions] == ["cards", "sync"]


def test_a_form_action_opens_its_form(example: ViewContext) -> None:
    plan = example.view_plan("project_table")
    assert [a.name for a in plan.row_actions] == ["open", "edit", "delete"]
    action = plan.action("new_project")
    assert action is not None
    assert action.form == "new_project"
    assert [f.component for f in plan.forms] == ["NewProjectForm", "EditProjectForm"]


def test_a_form_action_waits_for_the_forms_of_the_binding() -> None:
    plan = ViewContext(load_definition(EXAMPLE)).view_plan("project_table")
    assert [a.name for a in plan.row_actions] == ["open", "delete"]
    assert plan.action("new_project") is None
    assert plan.forms == []


def test_a_board_moves_a_card_with_its_operation(example: ViewContext, views: ViewContext) -> None:
    board = example.view_plan("task_board")
    assert board.move == 'updateTask(record.id, { status: value as Task["status"] })'
    assert [c.value for c in board.board_columns] == ["todo", "in_progress", "in_review", "done"]
    assert board.board_columns[1].limit == 8
    assert board.board_columns[1].color == "var(--status-progress)"
    other = views.view_plan("item_board")
    assert other.move == 'itemApi.update(record.id, { stage: value as Item["stage"] })'
    assert [c.label for c in other.board_columns] == ["New", "Open", "Closed"]


def test_a_card_without_a_title_shows_the_first_string_field(views: ViewContext) -> None:
    definition = views.definition
    assert definition_display(definition.entities["Item"]) == "code"
    assert definition_display(definition.entities["Member"]) == "name"
    card = views.view_plan("item_cards").card
    assert card is not None
    assert card.title == '{String(row.code ?? "")}'
    assert card.href == 'pageHref("item", { id: String(row.id) })'


def test_the_features_list_the_runtime_parts_that_the_views_need(views: ViewContext) -> None:
    assert views.features >= {"table", "cards", "board", "search", "select", "multi_select"}
    assert views.features >= {"boolean", "date_range", "badge", "avatar", "formatted"}
    edge_cases = ViewContext(load_definition(EXAMPLE.parent.parent / "edge-cases" / "app.yaml"))
    assert edge_cases.features == set()


def test_grid_classes_follow_the_breakpoints() -> None:
    grid = Grid(columns=4, gap="{spacing.4}", responsive={"lg": GridOverride(columns=2)})
    assert grid_classes(grid) == "grid grid-cols-4 gap-(--spacing-4) max-lg:grid-cols-2"
    assert grid_classes(None) == "grid grid-cols-1 gap-4"


def test_an_unused_lookups_parameter_gets_an_underscore() -> None:
    assert lookups_param("row.title") == "_lookups"
    assert lookups_param('lookups.person.get(row.ownerId ?? "")') == "lookups"


def test_a_field_format_applies_to_all_views_of_the_field(example: ViewContext) -> None:
    assert example.value("Project", "budget").format == "currency"
    assert example.value("Project", "budget", "number").format == "number"
    column = example.view_plan("project_table").columns
    assert next(c for c in column if c.name == "budget").cell.endswith('format="currency" />')
    widget = next(w for w in example.dashboard_plan("overview").widgets if w.name == "total_budget")
    assert widget.format == "currency"
    count = next(
        w for w in example.dashboard_plan("overview").widgets if w.name == "active_projects"
    )
    assert count.format == "number"


def test_a_currency_field_shows_its_values_in_its_currency() -> None:
    text = EXAMPLE.read_text().replace(
        "scale: 2, format: currency }", "scale: 2, format: currency, currency: EUR }"
    )
    context = ViewContext(load_definition_text(text), forms=True)
    budget = context.value("Project", "budget")
    assert budget.currency == "EUR"
    assert budget.text_expr == 'formatValue(row.budget, "currency", "EUR")'
    assert context.value("Project", "budget", "number").currency is None
    column = next(c for c in context.view_plan("project_table").columns if c.name == "budget")
    assert column.cell.endswith('format="currency" currency="EUR" />')
    widgets = context.dashboard_plan("overview").widgets
    assert next(w for w in widgets if w.name == "total_budget").currency == "EUR"


def test_a_board_with_a_responsive_hint_stacks_its_columns(example: ViewContext) -> None:
    plan = example.view_plan("task_board")
    assert plan.board_area_classes.endswith(" max-md:[&>[data-slot=scroll-area-scrollbar]]:hidden")
    assert plan.board_classes.endswith(" max-md:w-full max-md:flex-col")
    assert plan.column_classes.endswith(" max-md:w-full")


def test_a_chart_does_not_animate_without_motion() -> None:
    text = EXAMPLE.read_text().replace("motion: { $value: reduced }", "motion: { $value: none }")
    context = ViewContext(load_definition_text(text), forms=True)
    assert context.dashboard_plan("overview").motion == "none"


def test_a_page_does_not_show_an_action_that_its_top_bar_has() -> None:
    text = EXAMPLE.read_text().replace(", placement: page", "")
    example = ViewContext(load_definition_text(text), forms=True)
    bar = example.action_bar("pages.project_detail")
    assert bar.hidden_actions == ["pages.project_detail.actions.new_task"]
    assert all(a.name != "new_task" for a in bar.actions)
    # The top bar keeps the action.
    topbar = example.action_bar("ui.layouts.app_shell.topbar")
    assert [a.name for a in topbar.actions] == ["new_task"]
    # Other actions stay on the page.
    assert [a.name for a in example.action_bar("pages.task_detail").actions] == ["delete"]


def test_a_view_does_not_show_an_action_that_the_top_bar_of_its_pages_has(
    example: ViewContext,
) -> None:
    board = example.view_plan("task_board")
    assert board.hidden_actions == ["ui.views.task_board.actions.new_task"]
    assert board.actions == []
    assert [a.name for a in board.row_actions] == ["open", "edit"]


def test_an_action_with_placement_page_shows_on_the_page_only(example: ViewContext) -> None:
    bar = example.action_bar("pages.project_detail")
    assert (bar.hidden_actions, [a.name for a in bar.actions]) == ([], ["new_task"])
    # The top bar hides its own action on the page.
    [new_task] = example.action_bar("ui.layouts.app_shell.topbar").actions
    assert (new_task.only_pages, new_task.except_pages) == ((), ("project_detail",))


PLACEMENT = """\
version: 0
app: { name: shop, title: Shop }
entities:
  Item:
    crud: true
    display_field: name
    fields:
      name: { type: string, required: true }
pages:
  items:
    path: /items
    title: Items
    entity: Item
    actions:
      new_item: { kind: form, form: new_item, placement: topbar }
      export: { kind: custom, label: Export, placement: both }
  item:
    path: "/items/{id}"
    title: Item
    entity: Item
    actions:
      edit: { kind: form, form: edit_item }
ui:
  layouts:
    shell:
      topbar: { breadcrumbs: true }
  forms:
    new_item: { entity: Item, operation: create_item, fields: { name: {} } }
    edit_item: { entity: Item, operation: update_item, fields: { name: {} } }
  defaults: { layout: shell }
"""


def test_an_action_with_placement_topbar_shows_in_the_top_bar_of_its_page() -> None:
    context = ViewContext(load_definition_text(PLACEMENT), forms=True)

    page = context.action_bar("pages.items")
    topbar = context.action_bar("ui.layouts.shell.topbar")

    # `both` shows in the page header and in the top bar.
    assert [a.name for a in page.actions] == ["export"]
    assert page.hidden_actions == []
    assert [(a.name, a.element_id, a.only_pages) for a in topbar.actions] == [
        ("items_new_item", "pages.items.actions.new_item", ("items",)),
        ("items_export", "pages.items.actions.export", ("items",)),
    ]
    assert topbar.per_page


def test_the_top_bar_cannot_show_an_action_that_needs_the_record() -> None:
    text = PLACEMENT.replace("form: edit_item }", "form: edit_item, placement: topbar }")
    context = ViewContext(load_definition_text(text), forms=True)

    with pytest.raises(GenerationError, match="needs the record of its page"):
        context.action_bar("ui.layouts.shell.topbar")


ROOMS = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"


def test_a_computed_field_computes_its_value_in_the_views() -> None:
    context = ViewContext(load_definition(ROOMS), forms=True)
    cost = context.value("Booking", "cost")
    assert cost.expr == (
        "compute.round(compute.mul(compute.hours(row.startsAt, row.endsAt), "
        'compute.num(lookups.room.get(row.roomId ?? "")?.hourlyRate)), 2)'
    )
    assert cost.format == "currency"
    assert context.lookups_of("Booking", ["cost"]) == {"Room"}
    assert context.computed
