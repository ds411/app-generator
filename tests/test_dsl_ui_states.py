from textwrap import dedent

import pytest

from appgen.dsl import AppDefinition, load_definition_text
from appgen.dsl.ui.common import State
from appgen.dsl.ui.states import BUILT_IN_STATES, effective_states
from appgen.dsl.ui.views import CardsView, TableView
from appgen.dsl.validator import validate_definition

VALID = dedent(
    """\
    version: 0
    app: { name: demo, title: Demo }
    entities:
      Task:
        display_field: title
        fields:
          title: { type: string }
          due_date: { type: date }
    operations:
      create_task: { kind: create, entity: Task }
    ui:
      layouts:
        app_shell:
          sidebar: { mode: expanded, width: "{size.sidebar}" }
          topbar: { search: true }
          content: { padding: "{spacing.8}" }
          responsive:
            lg: { sidebar: { mode: icons } }
            md:
              sidebar: { mode: drawer }
              topbar: { search: false }
              content: { padding: "{spacing.4}" }
      views:
        task_table:
          kind: table
          entity: Task
          columns:
            title: {}
            due_date: { hide_below: md }
          actions:
            new_task: { kind: form, form: new_task, label: New task }
          states:
            loading: { indicator: spinner, text: Loading the tasks }
            empty:
              title: No tasks yet
              text: Create the first task of the project.
              icon: list-plus
              action: new_task
            error: { title: The tasks did not load, icon: cloud-off, action: retry }
        task_cards:
          kind: cards
          entity: Task
          grid:
            columns: 3
            gap: "{spacing.6}"
            responsive:
              lg: { columns: 2 }
              sm: { columns: 1, gap: "{spacing.4}" }
          states:
            empty: { title: Nothing to show }
      defaults:
        states:
          loading: { indicator: skeleton }
          error: { title: Something broke, icon: triangle-alert, action: retry }
    """
)


def load(text: str = VALID) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def codes(text: str) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in validate_definition(load(text))]


def test_valid_states_and_responsive_rules_have_no_problems() -> None:
    assert codes(VALID) == []


def test_loads_the_states_of_a_view() -> None:
    ui = load().ui
    assert ui is not None
    view = ui.views["task_table"]
    assert isinstance(view, TableView)

    states = view.states

    assert states is not None
    assert states.loading is not None
    assert (states.loading.indicator, states.loading.text) == ("spinner", "Loading the tasks")
    assert states.empty is not None
    assert (states.empty.title, states.empty.icon, states.empty.action) == (
        "No tasks yet",
        "list-plus",
        "new_task",
    )
    assert states.error is not None
    assert states.error.action == "retry"


def test_view_states_win_over_the_defaults() -> None:
    definition = load()
    assert definition.ui is not None

    states = effective_states(definition, definition.ui.views["task_table"])

    assert states.loading is not None
    assert states.loading.indicator == "spinner"
    assert states.error is not None
    assert states.error.title == "The tasks did not load"


def test_defaults_apply_when_a_view_does_not_define_a_state() -> None:
    definition = load()
    assert definition.ui is not None

    states = effective_states(definition, definition.ui.views["task_cards"])

    assert states.empty is not None
    assert states.empty.title == "Nothing to show"
    assert states.loading is not None
    assert states.loading.indicator == "skeleton"
    assert states.loading.text is None
    assert states.error is not None
    assert states.error.title == "Something broke"


def test_built_in_states_apply_last() -> None:
    definition = load(VALID[: VALID.index("  defaults:")])
    assert definition.ui is not None

    states = effective_states(definition, definition.ui.views["task_cards"])

    assert states.loading == BUILT_IN_STATES.loading
    assert states.error == State(
        title="Something went wrong", icon="triangle-alert", action="retry"
    )


def test_loads_the_responsive_rules_of_a_layout() -> None:
    ui = load().ui
    assert ui is not None

    responsive = ui.layouts["app_shell"].responsive

    assert list(responsive) == ["lg", "md"]
    lg_sidebar = responsive["lg"].sidebar
    assert lg_sidebar is not None
    assert lg_sidebar.mode == "icons"
    md = responsive["md"]
    assert md.sidebar is not None
    assert md.sidebar.mode == "drawer"
    assert md.topbar is not None
    assert md.topbar.search is False
    assert md.content is not None
    assert md.content.padding == "{spacing.4}"


def test_loads_the_responsive_rules_of_a_grid_and_a_column() -> None:
    ui = load().ui
    assert ui is not None
    cards = ui.views["task_cards"]
    table = ui.views["task_table"]
    assert isinstance(cards, CardsView)
    assert isinstance(table, TableView)

    assert cards.grid is not None
    assert cards.grid.responsive["lg"].columns == 2
    assert cards.grid.responsive["sm"].gap == "{spacing.4}"
    assert table.columns["due_date"].hide_below == "md"


def test_responsive_elements_have_ids() -> None:
    definition = load()

    assert definition.find("ui.layouts.app_shell.responsive.md.sidebar") is not None
    assert definition.find("ui.views.task_cards.grid.responsive.sm") is not None
    assert definition.find("ui.views.task_table.states.empty") is not None


@pytest.mark.parametrize(
    ("old", "new", "element_id"),
    [
        ("action: new_task", "action: add_task", "ui.views.task_table.states.empty"),
        (
            "cloud-off, action: retry",
            "cloud-off, action: reload",
            "ui.views.task_table.states.error",
        ),
        (
            "icon: triangle-alert, action: retry",
            "icon: triangle-alert, action: new_task",
            "ui.defaults.states.error",
        ),
        (
            "indicator: skeleton }",
            "indicator: skeleton, action: retry }",
            "ui.defaults.states.loading",
        ),
    ],
)
def test_state_actions_must_exist(old: str, new: str, element_id: str) -> None:
    assert old in VALID

    assert codes(VALID.replace(old, new, 1)) == [("unknown-reference", element_id)]
