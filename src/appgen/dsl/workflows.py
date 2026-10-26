"""The workflows of the entities: the states of an enum field and the allowed changes."""

from typing import Annotated

import pydantic

from appgen.dsl.element import Element, EntityName, MemberName, Text


class Transition(Element):
    """An allowed change of state: from one of the `from` values to the `to` value."""

    from_: Annotated[list[MemberName], pydantic.Field(alias="from", min_length=1)]
    """The values of the field before the change."""
    to: MemberName
    """The value of the field after the change."""
    label: Text | None = None
    run: MemberName | None = None
    """A custom operation of the entity that runs after the transition (ADR 0031)."""


class Workflow(Element):
    """A state machine on an enum field of an entity.

    The apps reject a change of the field that no transition allows. A
    change to the same value is not a transition.
    """

    entity: EntityName
    field: MemberName
    """An enum field of the entity. Its values are the states."""
    initial: MemberName | None = None
    """The state of a new record. Without it, a new record can have any state."""
    description: Text | None = None
    message: Text | None = None
    """The error message of a change that no transition allows."""
    transitions: Annotated[dict[MemberName, Transition], pydantic.Field(min_length=1)]

    def allows(self, before: str, after: str) -> bool:
        """Return True if a transition changes the field from `before` to `after`."""
        return before == after or any(
            before in t.from_ and t.to == after for t in self.transitions.values()
        )
