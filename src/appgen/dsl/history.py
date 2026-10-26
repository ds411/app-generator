"""The change log of the records of an entity (ADR 0040)."""

from typing import Annotated, Any

import pydantic

from appgen.dsl.element import Element, MemberName, Text


def history_input(value: object) -> object:
    """Return the mapping form of a shorthand: `true` becomes a mapping, `false` no history."""
    if value is True:
        return {}
    if value is False:
        return None
    return value


def history_schema(schema: dict[str, Any]) -> None:
    """Add the short form (`true` or `false`) to the JSON Schema of the key."""
    schema["anyOf"] = [{"type": "boolean"}, *schema.get("anyOf", [])]


class History(Element):
    """The change log of the records of an entity.

    Each create, change, and delete of a record adds an entry with the
    user, the time, and the old and the new values of the fields. A
    restore gives the old values of an entry back. The short form is
    `history: true`.
    """

    fields: Annotated[list[MemberName], pydantic.Field(min_length=1)] | None = None
    """The fields and the single relations that the log keeps. The default is all: the stored
    fields except the file fields, and the relations with a foreign key in the entity."""
    description: Text | None = None


type HistoryInput = Annotated[
    History | None,
    pydantic.BeforeValidator(history_input),
    pydantic.Field(json_schema_extra=history_schema),
]
"""A change log, `true`, or `false`."""
