"""The content of a page: the UI element that the page shows (ADR 0003)."""

from typing import Self

from pydantic import model_validator
from pydantic_core import PydanticCustomError

from appgen.dsl.element import Element, MemberName

_CONTENT_KEYS = ("view", "form", "dashboard", "custom")


class PageContent(Element):
    """What a page shows in its layout: one view, form, or dashboard, or a gap."""

    view: MemberName | None = None
    form: MemberName | None = None
    dashboard: MemberName | None = None
    custom: bool = False
    """Hand-written code gives the content (a generation gap)."""

    @model_validator(mode="after")
    def _one_content(self) -> Self:
        chosen = [key for key in _CONTENT_KEYS if getattr(self, key)]
        if len(chosen) != 1:
            raise PydanticCustomError(
                "page_content",
                "Set exactly one of the keys view, form, dashboard, or custom: true",
            )
        return self
