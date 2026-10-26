"""The notifications: notices in the apps for the changes of records (ADR 0041)."""

import re
from typing import Annotated, Literal

import pydantic

from appgen.dsl.access import OWNER_PATH_PATTERN
from appgen.dsl.element import Element, EntityName, MemberName, Text

type NotificationEvent = Literal["created", "changed"]
"""The changes of a record that give notices. A transition of a workflow is the third kind."""

TRANSITION_PATTERN = r"^([a-z][a-z0-9_]*\.)?[a-z][a-z0-9_]*$"
"""A transition: its name, or the name of its workflow and its name, for example `status.close`."""

type ReceiverPath = Annotated[str, pydantic.StringConstraints(pattern=OWNER_PATH_PATTERN)]
"""A relation, or a path of relations with dots, to the user entity: `project.members`."""

TEXT_VALUE = re.compile(r"\{([^{}]*)\}")
"""A value in the text of a notice: a name in braces, for example `{title}`."""


class Notification(Element):
    """The notices of a change of a record: who gets a notice, and its text (ADR 0041).

    The change is an event of the entity (`created`, or `changed` with
    `fields`), or a transition of a workflow of the entity. Each user at
    the end of a receiver path gets a notice, except the user that made
    the change.
    """

    entity: EntityName
    event: NotificationEvent | None = None
    """`created` or `changed`. A notification has `event` or `transition`, not both."""
    fields: Annotated[list[MemberName], pydantic.Field(min_length=1)] | None = None
    """Only for `changed`: the notice comes only when one of these fields or relations changes.

    The default is a change of any stored field or `many_to_one` relation.
    """
    transition: Annotated[str, pydantic.StringConstraints(pattern=TRANSITION_PATTERN)] | None = None
    """A transition of a workflow of the entity: its name, or `<workflow>.<transition>`."""
    receivers: Annotated[list[ReceiverPath], pydantic.Field(min_length=1)]
    """The users that get the notice: relations or paths of relations to the user entity.

    Each step is a `many_to_one` or a `many_to_many` relation of the
    entity of the step before, for example `assignee` or `project.members`.
    """
    text: Text
    """The text of the notice. A name in braces is a value of the record: `{title}`.

    The name is a stored field, or a `many_to_one` relation (the display
    value of its record).
    """
    description: Text | None = None

    def values(self) -> list[str]:
        """Return the names in braces of the text, without repeats, in text order."""
        return list(dict.fromkeys(m[1] for m in TEXT_VALUE.finditer(self.text)))

    def transition_parts(self) -> tuple[str | None, str] | None:
        """Return the workflow (or None) and the name of the transition, or None without one."""
        if self.transition is None:
            return None
        workflow, _, name = self.transition.rpartition(".")
        return workflow or None, name
