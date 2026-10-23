"""The theme, the layouts (app shells), and the navigation menus (ADR 0003)."""

from typing import Literal

import pydantic

from appgen.dsl.element import Element, MemberName, Text
from appgen.dsl.ui.common import Action, BreakpointName, IconName, TokenRef

type ColorMode = Literal["light", "dark", "system"]
type SidebarMode = Literal["expanded", "icons", "drawer", "hidden"]
"""`icons` shows only the icons. `drawer` hides the sidebar behind a menu button."""


class Theme(Element):
    """The theme settings of the app."""

    default_mode: ColorMode = "system"
    mode_toggle: bool = True
    """Show a light and dark mode switch in the top bar."""


class Sidebar(Element):
    """The sidebar region of a layout."""

    navigation: MemberName | None = None
    """The menu that the sidebar shows."""
    title: Text | None = None
    icon: IconName | None = None
    width: TokenRef | None = None
    """A `size` token."""
    mode: SidebarMode = "expanded"
    side: Literal["left", "right"] = "left"


class Topbar(Element):
    """The top bar region of a layout."""

    breadcrumbs: bool = True
    mode_toggle: bool = True
    search: bool = False
    actions: dict[MemberName, Action] = pydantic.Field(default_factory=dict[str, Action])


class Content(Element):
    """The content region of a layout, where the page shows."""

    max_width: TokenRef | None = None
    """A `size` token."""
    padding: TokenRef | None = None
    """A `spacing` token."""


class Footer(Element):
    """The optional footer region of a layout."""

    text: Text


class SidebarOverride(Element):
    """Sidebar keys that change on narrow screens."""

    mode: SidebarMode | None = None
    width: TokenRef | None = None


class TopbarOverride(Element):
    """Top bar keys that change on narrow screens."""

    breadcrumbs: bool | None = None
    mode_toggle: bool | None = None
    search: bool | None = None


class ContentOverride(Element):
    """Content keys that change on narrow screens."""

    max_width: TokenRef | None = None
    padding: TokenRef | None = None


class LayoutOverride(Element):
    """The region keys of a layout on screens narrower than a breakpoint."""

    sidebar: SidebarOverride | None = None
    topbar: TopbarOverride | None = None
    content: ContentOverride | None = None


class Layout(Element):
    """An app shell: a sidebar, a top bar, the content, and an optional footer."""

    sidebar: Sidebar | None = None
    topbar: Topbar | None = None
    content: Content | None = None
    footer: Footer | None = None
    responsive: dict[BreakpointName, LayoutOverride] = pydantic.Field(
        default_factory=dict[str, LayoutOverride]
    )
    """Overrides for screens narrower than a breakpoint. The smallest breakpoint wins."""


class MenuSubItem(Element):
    """An item below a menu item."""

    page: MemberName
    label: Text | None = None
    """The default is the title of the page."""
    icon: IconName | None = None


class MenuItem(MenuSubItem):
    """An item of a menu. It opens a page, and it can have one level of sub-items."""

    items: dict[MemberName, MenuSubItem] = pydantic.Field(default_factory=dict[str, MenuSubItem])


class MenuGroup(Element):
    """A group of menu items with a label."""

    label: Text | None = None
    icon: IconName | None = None
    collapsible: bool = False
    items: dict[MemberName, MenuItem] = pydantic.Field(default_factory=dict[str, MenuItem])


class Menu(Element):
    """A navigation menu. The items without a group show before the groups."""

    items: dict[MemberName, MenuItem] = pydantic.Field(default_factory=dict[str, MenuItem])
    groups: dict[MemberName, MenuGroup] = pydantic.Field(default_factory=dict[str, MenuGroup])
