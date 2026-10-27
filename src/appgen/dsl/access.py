"""The roles of the users and their permissions: the operations and the pages of each role."""

from typing import TYPE_CHECKING, Annotated, Literal

import pydantic

from appgen.dsl.element import Element, EntityName, MemberName, Text

if TYPE_CHECKING:
    from appgen.dsl.model import AppDefinition

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


SCOPE_PATH_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
"""A many-to-one relation, or a path of them with dots, for example `lesson.course`."""


class MembershipRole(Element):
    """A role of the memberships (ADR 0048): its operations on the records of its scopes."""

    label: Text | None = None
    operations: list[
        Annotated[str, pydantic.StringConstraints(pattern=r"^([a-z][a-z0-9_]*|\*)$")]
    ] = pydantic.Field(default_factory=list[str])
    """The operations of the entities of the scope, or `["*"]` for all of them."""

    def allows_operation(self, name: str) -> bool:
        """Return True if the role may call an operation on the records of its scope."""
        return ALL in self.operations or name in self.operations


class Memberships(Element):
    """The roles of the users in the records of a scope, for example a course (ADR 0048).

    A record of the membership entity gives its user (`user`) a role
    (`role_field`) in one record of the scope entity (`scope`). The role
    gives operations on the records of the scope: the scope record, and
    the records of the entities in `paths`. A user can have other roles
    in other scope records.
    """

    entity: EntityName
    """The membership entity, for example `Enrollment`."""
    user: MemberName
    """The many-to-one relation of the membership entity to the user entity."""
    scope: MemberName
    """The many-to-one relation to the scope entity, for example `course`."""
    role_field: MemberName
    """The enum field of the membership entity: its value is the role of the member."""
    roles: Annotated[dict[MemberName, MembershipRole], pydantic.Field(min_length=1)]
    """The roles by value of the role field."""
    paths: dict[
        EntityName, Annotated[str, pydantic.StringConstraints(pattern=SCOPE_PATH_PATTERN)]
    ] = pydantic.Field(default_factory=dict[str, str])
    """The path of many-to-one relations from each other entity of the scope to the scope entity."""


class Access(Element):
    """The roles of the users. It needs the section `auth`.

    The value of `role_field` (an enum field of the user entity) is the
    role of a user. A user may call the public operations and open the
    public pages of `auth`, and the operations and the pages of the role.
    With `memberships`, a user also has a role in each record of a scope
    (ADR 0048).
    """

    role_field: MemberName
    roles: Annotated[dict[MemberName, Role], pydantic.Field(min_length=1)]
    """The roles by value of the role field."""
    memberships: Memberships | None = None
    """The roles of the users in the records of a scope entity, from the membership records."""


def membership_scope(definition: AppDefinition) -> str | None:
    """Return the scope entity of the memberships (ADR 0048), or None.

    None if the definition has no memberships, or if the membership entity
    or its relation `scope` does not exist (the validator reports it).
    """
    memberships = definition.access.memberships if definition.access is not None else None
    entity = definition.entities.get(memberships.entity) if memberships is not None else None
    if memberships is None or entity is None:
        return None
    relation = entity.relations.get(memberships.scope)
    return relation.target if relation is not None else None


def scope_entities(definition: AppDefinition) -> dict[str, str]:
    """Return the entities of the scope of the memberships, and the path of each to the scope.

    The scope entity has the path `""`: its records are the scopes.
    """
    scope = membership_scope(definition)
    if scope is None or definition.access is None or definition.access.memberships is None:
        return {}
    return {scope: "", **definition.access.memberships.paths}


def membership_roles(definition: AppDefinition) -> dict[str, list[str]]:
    """Return the operations of each role of the memberships, sorted, with `*` expanded.

    `*` gives the operations of the entities of the scope, without the
    queries.
    """
    access = definition.access
    if access is None or access.memberships is None:
        return {}
    scoped = scope_entities(definition)
    everything = [
        name
        for name, op in definition.operations.items()
        if op.entity in scoped and op.kind != "query"
    ]
    return {
        name: sorted(everything if ALL in role.operations else role.operations)
        for name, role in access.memberships.roles.items()
    }
