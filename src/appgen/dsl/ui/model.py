"""The typed model of the UI part of an app definition (ADR 0003)."""

import pydantic

from appgen.dsl.element import Element, MemberName
from appgen.dsl.ui.layout import Layout, Menu, Theme
from appgen.dsl.ui.tokens import Tokens


class Defaults(Element):
    """Values that apply when a UI element does not set them."""

    layout: MemberName | None = None
    """The layout of the pages that do not set one."""


class UI(Element):
    """The `ui` section: the design tokens and the UI elements of the app."""

    theme: Theme | None = None
    tokens: Tokens | None = None
    layouts: dict[MemberName, Layout] = pydantic.Field(default_factory=dict[str, Layout])
    navigation: dict[MemberName, Menu] = pydantic.Field(default_factory=dict[str, Menu])
    defaults: Defaults | None = None
