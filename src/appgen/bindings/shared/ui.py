"""The app shell of the front-end apps: layouts, navigation, and pages (ADR 0003).

The shared UI templates in `templates/ui/` render the values of this
module. The Next.js and the React bindings add `ui_plan(definition)` to
the template context as `ui_plan`, and the helpers of `HELPERS` to the
template globals.

The responsive rules of a layout apply to screens narrower than a
breakpoint. A narrow screen is also narrower than each larger
breakpoint, so the overrides add up from the largest breakpoint to the
smallest, and the smallest breakpoint wins.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from appgen.bindings.shared import shadcn, theme
from appgen.dsl.model import AppDefinition, Page
from appgen.dsl.ui.layout import Layout, Menu, SidebarMode
from appgen.dsl.ui.routes import breadcrumbs, page_parent
from appgen.dsl.ui.tokens import TOKEN_REFERENCE_PATTERN
from appgen.gen.tokens import ResolvedToken, resolve_tokens

_REFERENCE = re.compile(TOKEN_REFERENCE_PATTERN)
_PARAM = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def css_var(ref: str) -> str:
    """Return the CSS variable of a token reference: `{size.wide}` gives `var(--size-wide)`."""
    match = _REFERENCE.match(ref)
    if match is None:
        raise ValueError(f"{ref!r} is not a token reference.")
    return theme.css_var(match.group(1))


def css_class_var(ref: str) -> str:
    """Return a token reference for a Tailwind CSS class: `{spacing.4}` gives `(--spacing-4)`.

    Use it after a utility prefix, for example `p-{{ css_class_var(ref) }}`.
    """
    return "(" + css_var(ref).removeprefix("var(").removesuffix(")") + ")"


def js(value: Any) -> str:
    """Return a value as a JavaScript literal, for example a string in double quotes."""
    return json.dumps(value, ensure_ascii=False)


_JSX_TEXT = re.compile(r"^[^{}<>&\n]*$")
_JSX_STRING = re.compile(r'^[^{}<>&"\\\n]*$')


def jsx_attr(value: Any) -> str:
    """Return a value as a JSX attribute value: `"..."`, or `{"..."}` for special characters."""
    if isinstance(value, str) and _JSX_STRING.match(value):
        return f'"{value}"'
    return "{" + js(value) + "}"


def jsx_text(text: str) -> str:
    """Return a text as a JSX child: the text itself, or `{"..."}` if it has special characters."""
    if _JSX_TEXT.match(text) and text == text.strip():
        return text
    return jsx_attr(text)


def page_params(path: str) -> list[str]:
    """Return the names of the path parameters of a page path, in order."""
    return _PARAM.findall(path)


@dataclass(frozen=True, slots=True)
class Step:
    """The rules of a layout on screens narrower than one breakpoint."""

    breakpoint: str
    query: str
    """The media query, for example `(width < 768px)`."""
    variant: str
    """The Tailwind CSS variant, for example `max-md`."""
    element_ids: tuple[str, ...]
    """The IDs of the override and of its regions, for the traces."""
    sidebar_mode: SidebarMode | None = None
    sidebar_width: str | None = None
    """A CSS value, for example `var(--size-sidebar-icons)`."""


@dataclass(slots=True)
class Visibility:
    """Where a part of the top bar shows: on wide screens, and below each breakpoint."""

    base: bool
    overrides: list[tuple[str, bool]] = field(default_factory=list[tuple[str, bool]])
    """The Tailwind CSS variant and the value of each override, largest breakpoint first."""

    @property
    def shown(self) -> bool:
        """True if the part shows on some screens."""
        return self.base or any(value for _, value in self.overrides)

    def classes(self, display: str = "flex") -> str:
        """Return the classes that show and hide the part, for example `flex max-md:hidden`."""
        parts = [display if self.base else "hidden"]
        parts += [
            f"{variant}:{display if value else 'hidden'}" for variant, value in self.overrides
        ]
        return " ".join(parts)


@dataclass(slots=True)
class LayoutPlan:
    """The values of a layout that the app shell template needs."""

    name: str
    layout: Layout
    sidebar_mode: SidebarMode = "expanded"
    sidebar_width: str | None = None
    steps: list[Step] = field(default_factory=list[Step])
    """The responsive steps, largest breakpoint first."""
    breadcrumbs: Visibility = field(default_factory=lambda: Visibility(base=False))
    mode_toggle: Visibility = field(default_factory=lambda: Visibility(base=False))
    search: Visibility = field(default_factory=lambda: Visibility(base=False))
    content_classes: str = ""

    @property
    def sidebar_steps(self) -> list[Step]:
        """The steps that change the sidebar mode, smallest breakpoint first."""
        return [step for step in reversed(self.steps) if step.sidebar_mode is not None]

    @property
    def sidebar_modes(self) -> list[SidebarMode]:
        """All sidebar modes of the layout, in a fixed order."""
        modes = {self.sidebar_mode, *(s.sidebar_mode for s in self.steps if s.sidebar_mode)}
        return [mode for mode in ("expanded", "icons", "drawer", "hidden") if mode in modes]

    @property
    def sidebar_classes(self) -> str:
        """Return the classes that set the sidebar widths of the shell.

        A width applies to the sidebar mode of the same screen size: the
        icon width in the `icons` mode, else the full width.
        """
        classes: list[str] = []
        mode = self.sidebar_mode
        widths = [("", self.sidebar_mode, self.sidebar_width)]
        widths += [(f"{s.variant}:", s.sidebar_mode, s.sidebar_width) for s in self.steps]
        for prefix, step_mode, width in widths:
            mode = step_mode or mode
            if width is not None:
                name = "--shell-sidebar-width-icon" if mode == "icons" else "--shell-sidebar-width"
                classes.append(f"{prefix}[{name}:{width}]")
        return " ".join(classes)


@dataclass(frozen=True, slots=True)
class PageInfo:
    """A page, as the navigation, the breadcrumbs, and the search see it."""

    name: str
    page: Page
    parent: str | None
    layout: str | None
    """The effective layout: the page layout, else `ui.defaults.layout`."""
    params: tuple[str, ...]
    crumbs: tuple[tuple[str, str, bool], ...]
    """The breadcrumbs: (page name, label, label from the record)."""


@dataclass(slots=True)
class UiPlan:
    """The app shell of a definition: layouts, menus, and pages."""

    layouts: dict[str, LayoutPlan] = field(default_factory=dict[str, LayoutPlan])
    menus: dict[str, Menu] = field(default_factory=dict[str, Menu])
    """The menus that a sidebar shows."""
    pages: dict[str, PageInfo] = field(default_factory=dict[str, PageInfo])
    search: bool = False
    """True if a top bar has the page search."""
    breadcrumbs: bool = False
    """True if a top bar has the breadcrumbs."""
    record_entities: list[str] = field(default_factory=list[str])
    """The entities that a breadcrumb shows a record of, sorted by name."""
    mode_toggle: bool = False
    """True if the app has the switch for the color mode."""
    typography: set[str] = field(default_factory=set[str])
    """The utility classes of the typography tokens, for example `typography-heading`."""

    def text_class(self, name: str, fallback: str) -> str:
        """Return the utility of a typography token, or the fallback classes without it."""
        utility = f"typography-{theme.css_name(name)}"
        return utility if utility in self.typography else fallback

    def pages_of(self, layout: str | None) -> list[PageInfo]:
        """Return the pages with an effective layout, in definition order."""
        return [info for info in self.pages.values() if info.layout == layout]


def ui_plan(definition: AppDefinition) -> UiPlan:
    """Return the app shell of a definition."""
    plan = UiPlan(
        mode_toggle=shadcn.has_mode_toggle(definition),
        typography={utility.name for utility in theme.build_theme(definition).utilities},
    )
    ui = definition.ui
    default_layout = ui.defaults.layout if ui and ui.defaults else None
    for name, page in definition.pages.items():
        crumbs = tuple(
            (c.page, c.label, c.from_record) for c in breadcrumbs(definition.pages, name)
        )
        plan.pages[name] = PageInfo(
            name=name,
            page=page,
            parent=page_parent(definition.pages, name),
            layout=page.layout or default_layout,
            params=tuple(page_params(page.path)),
            crumbs=crumbs,
        )
    entities = {
        definition.pages[crumb[0]].entity
        for info in plan.pages.values()
        if info.layout is not None
        for crumb in info.crumbs
        if crumb[2]
    }
    plan.record_entities = sorted(entity for entity in entities if entity is not None)
    if ui is None:
        return plan
    shown = {layout.sidebar.navigation for layout in ui.layouts.values() if layout.sidebar}
    plan.menus = {name: menu for name, menu in ui.navigation.items() if name in shown}
    breakpoints = _breakpoints(resolve_tokens(definition))
    for name, layout in ui.layouts.items():
        plan.layouts[name] = _layout_plan(name, layout, breakpoints)
    plan.search = any(layout.search.shown for layout in plan.layouts.values())
    plan.breadcrumbs = any(layout.breadcrumbs.shown for layout in plan.layouts.values())
    return plan


def _breakpoints(tokens: list[ResolvedToken]) -> dict[str, str]:
    return {
        token.path.split(".", 1)[1]: theme.css_value(token, token.light)
        for token in tokens
        if token.group == "breakpoint"
    }


def _size(value: str) -> float:
    """Return a CSS length as a number for sorting. `rem` and `em` count as 16px."""
    match = re.match(r"^([0-9.]+)(px|rem|em)?$", value.strip())
    if match is None:
        return 0.0
    number = float(match.group(1))
    return number * 16 if match.group(2) in ("rem", "em") else number


def _layout_plan(name: str, layout: Layout, breakpoints: dict[str, str]) -> LayoutPlan:
    plan = LayoutPlan(name=name, layout=layout)
    sidebar, topbar, content = layout.sidebar, layout.topbar, layout.content
    if sidebar is not None:
        plan.sidebar_mode = sidebar.mode
        plan.sidebar_width = css_var(sidebar.width) if sidebar.width else None
    if topbar is not None:
        plan.breadcrumbs = Visibility(topbar.breadcrumbs)
        plan.mode_toggle = Visibility(topbar.mode_toggle)
        plan.search = Visibility(topbar.search)
    content_classes = ["mx-auto", "w-full"]
    if content is not None and content.max_width:
        content_classes.append(f"max-w-{css_class_var(content.max_width)}")
    if content is not None and content.padding:
        content_classes.append(f"p-{css_class_var(content.padding)}")
    else:
        content_classes.append("p-6")
    ordered = sorted(
        layout.responsive.items(), key=lambda item: -_size(breakpoints.get(item[0], "0"))
    )
    for breakpoint, override in ordered:
        variant = f"max-{breakpoint}"
        ids = [override.id]
        mode: SidebarMode | None = None
        width: str | None = None
        if override.sidebar is not None:
            ids.append(override.sidebar.id)
            mode = override.sidebar.mode
            width = css_var(override.sidebar.width) if override.sidebar.width else None
        if override.topbar is not None:
            ids.append(override.topbar.id)
            for key, visibility in (
                ("breadcrumbs", plan.breadcrumbs),
                ("mode_toggle", plan.mode_toggle),
                ("search", plan.search),
            ):
                value = getattr(override.topbar, key)
                if value is not None:
                    visibility.overrides.append((variant, value))
        if override.content is not None:
            ids.append(override.content.id)
            if override.content.max_width:
                content_classes.append(
                    f"{variant}:max-w-{css_class_var(override.content.max_width)}"
                )
            if override.content.padding:
                content_classes.append(f"{variant}:p-{css_class_var(override.content.padding)}")
        plan.steps.append(
            Step(
                breakpoint=breakpoint,
                query=f"(width < {breakpoints.get(breakpoint, '0px')})",
                variant=variant,
                element_ids=tuple(ids),
                sidebar_mode=mode,
                sidebar_width=width,
            )
        )
    plan.content_classes = " ".join(content_classes)
    return plan


def menu_icons(menu: Menu) -> list[str]:
    """Return the icons of a menu, of its groups, and of its items, sorted by name.

    An item without an icon gets the icon `circle`, so that it shows when
    the sidebar shows only the icons.
    """
    items = [*menu.items.values(), *(i for g in menu.groups.values() for i in g.items.values())]
    icons = {group.icon for group in menu.groups.values()}
    icons |= {item.icon or "circle" for item in items}
    icons |= {sub.icon for item in items for sub in item.items.values()}
    return sorted(icon for icon in icons if icon is not None)


def menu_has_sub_items(menu: Menu) -> bool:
    """Return True if an item of a menu has sub-items."""
    items = [*menu.items.values(), *(i for g in menu.groups.values() for i in g.items.values())]
    return any(item.items for item in items)


HELPERS: dict[str, Callable[..., Any]] = {
    "menu_icons": menu_icons,
    "menu_has_sub_items": menu_has_sub_items,
    "css_var": css_var,
    "css_class_var": css_class_var,
    "page_params": page_params,
    "js": js,
    "jsx_attr": jsx_attr,
    "jsx_text": jsx_text,
}
"""The helpers of the shared UI templates."""
