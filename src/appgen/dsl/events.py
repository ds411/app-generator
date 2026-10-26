"""The events of the entities: custom operations that run after a change of a record (ADR 0031)."""

from typing import Annotated, Any, Literal

import pydantic

from appgen.dsl.element import MEMBER_NAME_PATTERN, Element, MemberName, Text

type EventName = Literal["created", "changed", "deleted"]
"""The changes of a record that start an event."""
EVENT_NAMES: tuple[str, ...] = EventName.__value__.__args__


def event_input(value: object) -> object:
    """Return the mapping form of a shorthand: the name of an operation becomes a mapping."""
    if isinstance(value, str):
        return {"operation": value}
    return value


def event_schema(schema: dict[str, Any]) -> None:
    """Add the short form (the name of an operation) to the JSON Schema of an event."""
    short = {"type": "string", "pattern": MEMBER_NAME_PATTERN}
    long = [{"$ref": schema.pop("$ref")}] if "$ref" in schema else schema.pop("anyOf", [])
    schema["anyOf"] = [short, *long]


class Event(Element):
    """A custom operation of the entity that runs after a change of a record.

    The operation runs in the transaction of the change, after the change
    is in the database. An error of the operation rolls back the change.
    The short form is the name of the operation: `created: notify_owner`.
    """

    operation: MemberName
    """A custom operation of the entity, without required params. It gets the record."""
    fields: Annotated[list[MemberName], pydantic.Field(min_length=1)] | None = None
    """Only for `changed`: the event runs only when one of these fields changes."""
    description: Text | None = None


type EventInput = Annotated[
    Event,
    pydantic.BeforeValidator(event_input),
    pydantic.Field(json_schema_extra=event_schema),
]
"""An event, or the name of its operation."""
