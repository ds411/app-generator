"""Routes: the parent of each page and its breadcrumbs (ADR 0003).

The breadcrumbs come from the route structure. The parent of a page is
the page whose path is the longest prefix of the page path, segment by
segment. Path parameters match each other, whatever their names.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from appgen.dsl.model import Page


@dataclass(frozen=True, slots=True)
class Breadcrumb:
    """One step of the breadcrumbs of a page."""

    page: str
    label: str
    from_record: bool
    """True if the binding shows the display field of the record, not the label."""


def path_segments(path: str) -> tuple[str, ...]:
    """Return the segments of a page path. Each path parameter becomes `{}`."""
    return tuple("{}" if part.startswith("{") else part for part in path.split("/") if part)


def page_parent(pages: Mapping[str, Page], name: str) -> str | None:
    """Return the name of the parent page of a page, or None for a root page.

    Two pages with the same path are an error that the validator reports.
    Here the first of them wins.
    """
    segments = path_segments(pages[name].path)
    best: tuple[int, str] | None = None
    for other, page in pages.items():
        prefix = path_segments(page.path)
        size = len(prefix)
        is_prefix = other != name and size < len(segments) and segments[:size] == prefix
        if is_prefix and (best is None or size > best[0]):
            best = (size, other)
    return best[1] if best else None


def breadcrumbs(pages: Mapping[str, Page], name: str) -> list[Breadcrumb]:
    """Return the breadcrumbs of a page, from the root page to the page."""
    chain: list[str] = []
    current: str | None = name
    while current is not None:
        chain.append(current)
        current = page_parent(pages, current)
    result: list[Breadcrumb] = []
    for page_name in reversed(chain):
        page = pages[page_name]
        has_param = "{}" in path_segments(page.path)
        from_record = page.breadcrumb is None and page.entity is not None and has_param
        result.append(Breadcrumb(page_name, page.breadcrumb or page.title, from_record))
    return result
