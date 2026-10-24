"""The content of a page: the UI element that the page shows (ADR 0003)."""

from typing import Annotated, Literal, Self

import pydantic
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


type Region = Literal["title", "actions", "content"]
"""A part of a page: the title and the description, the page actions, or the content."""


class PageArrangement(Element):
    """Layout hints of a page: the order of its regions in a grid of columns.

    The regions fill the grid in their order. Each region takes one cell,
    and `content` takes a full row. A region that the list does not have
    does not show, but each page shows its content.
    """

    regions: Annotated[list[Region], pydantic.Field(min_length=1)]
    columns: Annotated[int, pydantic.Field(ge=1, le=4)] = 2
    """The grid columns on medium and wider screens. Narrow screens have one column."""

    @model_validator(mode="after")
    def _regions(self) -> Self:
        if len(set(self.regions)) != len(self.regions):
            raise PydanticCustomError("page_regions", "Give each region one time only")
        if "content" not in self.regions:
            raise PydanticCustomError("page_regions", "The regions must have 'content'")
        return self
