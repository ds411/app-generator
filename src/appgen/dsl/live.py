"""The live updates of the records of an entity (ADR 0051)."""

from typing import Annotated, Any

import pydantic

from appgen.dsl.element import Element, Text


def live_input(value: object) -> object:
    """Return the mapping form of a shorthand: `true` becomes a mapping, `false` no updates."""
    if value is True:
        return {}
    if value is False:
        return None
    return value


def live_schema(schema: dict[str, Any]) -> None:
    """Add the short form (`true` or `false`) to the JSON Schema of the key."""
    schema["anyOf"] = [{"type": "boolean"}, *schema.get("anyOf", [])]


class Live(Element):
    """The live updates of the records of an entity.

    The apps send an event for each create, change, and delete of a record
    to the users that may read the record, and the open views of the
    entity show the change. The short form is `live: true`.
    """

    description: Text | None = None


type LiveInput = Annotated[
    Live | None,
    pydantic.BeforeValidator(live_input),
    pydantic.Field(json_schema_extra=live_schema),
]
"""Live updates, `true`, or `false`."""
