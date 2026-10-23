"""The typed model of the UI part of an app definition (ADR 0003)."""

from appgen.dsl.element import Element
from appgen.dsl.ui.tokens import Tokens


class UI(Element):
    """The `ui` section: the design tokens and the UI elements of the app."""

    tokens: Tokens | None = None
