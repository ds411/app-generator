"""The typed model of the UI part of an app definition (ADR 0003)."""

from typing import Annotated

import pydantic

from appgen.dsl.element import Element, MemberName
from appgen.dsl.ui.layout import Layout, Menu, Theme
from appgen.dsl.ui.tokens import Tokens
from appgen.dsl.ui.views import BadgeSet, View


class Defaults(Element):
    """Values that apply when a UI element does not set them."""

    layout: MemberName | None = None
    """The layout of the pages that do not set one."""
    page_size: Annotated[int, pydantic.Field(ge=1)] | None = None
    """The page size of the lists that do not set one."""


class UI(Element):
    """The `ui` section: the design tokens and the UI elements of the app."""

    theme: Theme | None = None
    tokens: Tokens | None = None
    layouts: dict[MemberName, Layout] = pydantic.Field(default_factory=dict[str, Layout])
    navigation: dict[MemberName, Menu] = pydantic.Field(default_factory=dict[str, Menu])
    badges: dict[MemberName, BadgeSet] = pydantic.Field(default_factory=dict[str, BadgeSet])
    views: dict[MemberName, View] = pydantic.Field(default_factory=dict[str, View])
    defaults: Defaults | None = None
