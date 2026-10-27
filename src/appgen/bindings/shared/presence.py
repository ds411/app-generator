"""The other users on a record page (ADR 0052): the pages with `presence`, for all bindings.

A page with `presence` is a detail page of a live entity. The page tells
the server that the user is on the record, each few seconds and when the
user starts or stops to type. The server keeps the users on each record
in the broker of the live updates (ADR 0051), and sends their changes to
the other users on the record through the stream.
"""

from dataclasses import dataclass

from appgen.bindings.shared.auth import kind_operations
from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.views import DetailView
from appgen.gen.binding import Output


@dataclass(frozen=True, slots=True)
class PresencePlan:
    """A page with `presence`: the record page that shows the other users on the record."""

    page: str
    """The name of the page."""
    page_id: str
    """The element ID of the page: the traces of the code name it."""
    entity: str
    read: str
    """The read operation of the entity: the calls of the page need its permission."""


def presence_plans(definition: AppDefinition) -> dict[str, PresencePlan]:
    """Return the pages with `presence`, by name (the validator allows only valid pages)."""
    ui = definition.ui
    if ui is None or definition.auth is None:
        return {}
    found: dict[str, PresencePlan] = {}
    for name, page in definition.pages.items():
        content = page.content
        view = ui.views.get(content.view or "") if page.presence and content is not None else None
        if not isinstance(view, DetailView):
            continue
        read = kind_operations(definition, view.entity).get("read")
        if read is None:
            continue
        found[name] = PresencePlan(name, page.id, view.entity, read)
    return found


def presence_entities(definition: AppDefinition) -> dict[str, list[PresencePlan]]:
    """Return the pages with `presence` of each entity, by entity, in the order of the pages."""
    found: dict[str, list[PresencePlan]] = {}
    for plan in presence_plans(definition).values():
        found.setdefault(plan.entity, []).append(plan)
    return found


def presence_rules() -> tuple[Output, ...]:
    """Return the output rules of the front ends: the avatars and the note of the typing.

    The bindings put `presence_plans` in their context as `presences`.
    """
    return tuple(
        Output(
            template=f"ui/features/record-presence/{template}.j2",
            path=f"src/features/record-presence/{path}",
            when="presences",
        )
        for template, path in (
            ("index.ts", "index.ts"),
            ("record-presence.tsx", "ui/record-presence.tsx"),
        )
    )
