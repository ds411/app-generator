"""Tests of the app shell values of the front-end bindings (`appgen.bindings.shared.ui`)."""

from pathlib import Path

import pytest

from appgen.bindings.shared.ui import (
    RegionPlan,
    css_class_var,
    css_var,
    jsx_attr,
    jsx_text,
    menu_icons,
    page_grid,
    page_regions,
    ui_plan,
)
from appgen.dsl import load_definition

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"
LAYOUTS = Path(__file__).parent / "fixtures" / "react-layouts.yaml"


def test_a_token_reference_gives_its_css_variable() -> None:
    assert css_var("{size.sidebar_icons}") == "var(--size-sidebar-icons)"
    assert css_var("{spacing.4}") == "var(--spacing-4)"
    assert css_var("{color.status.neutral}") == "var(--status-neutral)"
    assert css_class_var("{spacing.8}") == "(--spacing-8)"
    with pytest.raises(ValueError, match="not a token reference"):
        css_var("size.sidebar")


def test_jsx_values_keep_each_character() -> None:
    assert jsx_attr("Books") == '"Books"'
    assert jsx_attr('Say "hi"') == '{"Say \\"hi\\""}'
    assert jsx_text("Plain text") == "Plain text"
    assert jsx_text("Tom & Jerry") == '{"Tom & Jerry"}'
    assert jsx_text("{x}") == '{"{x}"}'


def test_the_responsive_rules_add_up_from_the_largest_breakpoint() -> None:
    plan = ui_plan(load_definition(EXAMPLE)).layouts["app_shell"]

    assert [step.breakpoint for step in plan.steps] == ["lg", "md"]
    assert [step.query for step in plan.steps] == ["(width < 1024px)", "(width < 768px)"]
    assert [(s.breakpoint, s.sidebar_mode) for s in plan.sidebar_steps] == [
        ("md", "drawer"),
        ("lg", "icons"),
    ]
    assert plan.sidebar_modes == ["expanded", "icons", "drawer"]
    assert plan.sidebar_classes == (
        "[--shell-sidebar-width:var(--size-sidebar)] "
        "max-lg:[--shell-sidebar-width-icon:var(--size-sidebar-icons)]"
    )
    assert plan.content_classes == (
        "mx-auto w-full max-w-(--size-content) p-(--spacing-8) "
        "max-lg:p-(--spacing-6) max-md:p-(--spacing-4)"
    )
    assert plan.search.classes() == "flex max-md:hidden"
    assert plan.breadcrumbs.classes("block") == "block"


def test_a_part_of_the_top_bar_can_show_only_on_small_screens() -> None:
    plan = ui_plan(load_definition(LAYOUTS)).layouts["library"]

    assert plan.breadcrumbs.shown
    assert plan.breadcrumbs.classes("block") == "hidden max-lg:block"
    assert plan.mode_toggle.classes("block") == "hidden max-sm:block"
    assert plan.sidebar_modes == ["expanded", "icons", "hidden"]


def test_the_plan_has_the_pages_menus_and_record_breadcrumbs() -> None:
    definition = load_definition(LAYOUTS)
    plan = ui_plan(definition)

    assert list(plan.menus) == ["main"]
    assert plan.pages["home"].layout == "plain"
    assert plan.pages["books"].layout == "library"
    assert plan.pages["chapter_detail"].parent == "book_detail"
    assert plan.pages["chapter_detail"].params == ("book_id", "id")
    assert plan.pages["settings"].crumbs[-1] == ("settings", "Preferences", False)
    assert plan.record_entities == ["Book", "Chapter"]
    assert plan.search and plan.breadcrumbs and plan.mode_toggle
    assert [p.name for p in plan.pages_of("bare")] == ["about"]
    assert menu_icons(definition.ui.navigation["main"]) == ["book-open", "circle", "settings"]  # pyright: ignore[reportOptionalMemberAccess]


def test_the_typography_class_falls_back_without_its_token() -> None:
    assert ui_plan(load_definition(EXAMPLE)).text_class("heading", "x") == "typography-heading"
    assert ui_plan(load_definition(LAYOUTS)).text_class("heading", "x") == "x"


def test_the_regions_of_a_page_fill_the_grid_in_their_order() -> None:
    definition = load_definition(EXAMPLE)
    page = definition.pages["project_detail"]
    assert page.arrangement is not None
    assert page_grid(page) == "grid gap-4 md:grid-cols-2"
    assert page_regions(page, has_actions=True) == [
        RegionPlan("title", "min-w-0"),
        RegionPlan("actions", "flex flex-wrap items-start gap-2 md:justify-end"),
        RegionPlan("content", "min-w-0 md:col-span-2"),
    ]
    # A page without actions has no actions region.
    assert [r.name for r in page_regions(page, has_actions=False)] == ["title", "content"]
    one = page.model_copy(
        update={"arrangement": page.arrangement.model_copy(update={"columns": 1})}
    )
    assert page_grid(one) == "grid gap-4"
    assert [r.classes for r in page_regions(one, has_actions=True)][1] == (
        "flex flex-wrap items-start gap-2"
    )
    assert page_regions(definition.pages["projects"], has_actions=True) == []
