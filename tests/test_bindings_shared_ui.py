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
    menu_labels,
    page_grid,
    page_regions,
    ui_plan,
)
from appgen.dsl import load_definition, load_definition_text
from appgen.gen import find_binding, generate

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


@pytest.mark.parametrize(
    ("binding_name", "development"),
    [("nextjs", 'process.env.NODE_ENV === "development"'), ("react", "import.meta.env.DEV")],
)
def test_a_stub_widget_shows_its_element_id_only_in_development(
    binding_name: str, development: str
) -> None:
    result = generate(load_definition(EXAMPLE), find_binding(binding_name))
    stubs = {f.path: f.content for f in result.files if f.path.endswith(".ext.tsx")}

    # The custom widget, the custom form widget, and the custom detail tabs.
    assert {
        "src/widgets/overview/ui/workload-widget.ext.tsx",
        "src/features/assign-task-form/ui/assignee-id-widget.ext.tsx",
        "src/widgets/task-detail/ui/activity-tab.ext.tsx",
    } <= set(stubs)
    for path, content in stubs.items():
        line = next(line for line in content.splitlines() if "Not implemented yet" in line)
        element_id = content.splitlines()[1].split()[2]
        # The example has translations, so the stub translates its text.
        assert line.strip() == (
            f'{{{development} ? t("Not implemented yet: {{element}}", '
            f'{{ element: "{element_id}" }}) : t("Not available yet.")}}'
        ), path


def test_a_breadcrumb_uses_the_label_of_the_menu_item_of_its_page() -> None:
    plan = ui_plan(load_definition(EXAMPLE))
    # The menu item of the page task_board has the label "Task board"; the page title is "Tasks".
    assert plan.pages["task_board"].crumbs[-1] == ("task_board", "Task board", False)
    assert plan.pages["task_detail"].crumbs[1] == ("task_board", "Task board", False)
    # A menu item without a label keeps the page title, and a record keeps its label source.
    assert plan.pages["projects"].crumbs[-1] == ("projects", "Projects", False)
    assert plan.pages["task_detail"].crumbs[-1] == ("task_detail", "Task", True)


def test_a_page_that_is_not_in_the_menu_keeps_its_title() -> None:
    definition = load_definition_text(
        "version: 0\napp: { name: a, title: A }\n"
        "entities:\n  Note:\n    fields: { text: { type: text } }\n"
        "pages:\n"
        "  home: { path: /, title: Home }\n"
        "  notes: { path: /notes, title: Notes, entity: Note }\n"
        "  archive: { path: /notes/archive, title: Archive }\n"
        "  tags: { path: /tags, title: Tags, breadcrumb: Labels }\n"
        "ui:\n"
        "  defaults: { layout: shell }\n"
        "  layouts:\n"
        "    shell:\n"
        "      sidebar: { navigation: main }\n"
        "      topbar: { breadcrumbs: true }\n"
        "  navigation:\n"
        "    main:\n"
        "      items:\n"
        "        notes: { page: notes, label: All notes }\n"
        "        tags: { page: tags, label: All tags }\n"
    )
    assert menu_labels(definition, "shell") == {"notes": "All notes", "tags": "All tags"}
    # The breadcrumb key of a page wins over the menu label.
    assert ui_plan(definition).pages["tags"].crumbs[-1] == ("tags", "Labels", False)
    crumbs = ui_plan(definition).pages["archive"].crumbs
    assert [label for _, label, _ in crumbs] == ["Home", "All notes", "Archive"]
