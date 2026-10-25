"""The roles of the users and their permissions: the operations and the pages of each role."""

from typing import Annotated, Literal

import pydantic

from appgen.dsl.element import Element, EntityName, MemberName, Text

ALL = "*"
"""In a list of operations or pages: all of them."""

type RecordAction = Literal["read", "change"]
"""`read`: the lists and the reads. `change`: the creates, the changes, and the deletes."""


type ConditionValue = pydantic.StrictStr | pydantic.StrictInt | pydantic.StrictBool
"""A value of a condition of a record rule: a text, an integer, or a boolean."""

type ConditionValues = Annotated[list[ConditionValue], pydantic.Field(min_length=1)]
"""The values of a condition with more than one value: the field has one of them."""

OWNER_PATH_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
"""A relation, or a path of relations with dots, for example `project.team.members`."""


class RecordRule(Element):
    """A record rule: the role uses only some records of an entity (ADR 0018, ADR 0025).

    The records of the rule belong to the user (`owner`), and have the
    values of the conditions (`where`). A rule needs `owner`, `where`,
    or both.
    """

    owner: Annotated[str, pydantic.StringConstraints(pattern=OWNER_PATH_PATTERN)] | None = None
    """A relation or a path of relations to the user entity, for example `project.team.members`.

    Each step is a relation of the entity of the step before. The last
    step is a `many_to_one` or a `many_to_many` relation to the user
    entity. A record belongs to each user at the end of the path.
    """
    where: dict[MemberName, ConditionValue | ConditionValues] = pydantic.Field(
        default_factory=dict[str, "ConditionValue | ConditionValues"]
    )
    """The conditions: a value of a field, or a list of values (one of them), by field name."""

    def conditions(self) -> dict[str, list[str | int | bool]]:
        """Return the conditions with a list of values for each field, in source order."""
        return {
            name: list(value) if isinstance(value, list) else [value]
            for name, value in self.where.items()
        }

    operations: Annotated[list[RecordAction], pydantic.Field(min_length=1)] = pydantic.Field(
        default_factory=lambda: ["read", "change"]
    )
    """The operations that the rule applies to: `read`, `change`, or both (the default)."""


class Role(Element):
    """A role: the operations and the pages that its users may use (ADR 0012)."""

    label: Text | None = None
    operations: list[
        Annotated[str, pydantic.StringConstraints(pattern=r"^([a-z][a-z0-9_]*|\*)$")]
    ] = pydantic.Field(default_factory=list[str])
    """The operations that the role may call, or `["*"]` for all operations."""
    pages: list[Annotated[str, pydantic.StringConstraints(pattern=r"^([a-z][a-z0-9_]*|\*)$")]] = (
        pydantic.Field(default_factory=list[str])
    )
    """The pages that the role may open, or `["*"]` for all pages."""
    records: dict[EntityName, RecordRule] = pydantic.Field(default_factory=dict[str, RecordRule])
    """The record rules of the role, by entity: the role uses only the records of the rule."""

    def allows_operation(self, name: str) -> bool:
        """Return True if the role may call an operation."""
        return ALL in self.operations or name in self.operations

    def allows_page(self, name: str) -> bool:
        """Return True if the role may open a page."""
        return ALL in self.pages or name in self.pages


class Access(Element):
    """The roles of the users. It needs the section `auth`.

    The value of `role_field` (an enum field of the user entity) is the
    role of a user. A user may call the public operations and open the
    public pages of `auth`, and the operations and the pages of the role.
    """

    role_field: MemberName
    roles: Annotated[dict[MemberName, Role], pydantic.Field(min_length=1)]
    """The roles by value of the role field."""
