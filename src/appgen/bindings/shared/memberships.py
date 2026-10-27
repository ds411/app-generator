"""The memberships of the front ends (ADR 0048): the roles of the users in the records of a scope.

A membership record gives its user a role in one record of the scope
entity. The table of the permissions (`@/shared/lib/permissions`) has
the operations of each role and the path of each entity of the scope.
The server of the Next.js app and the mock store of the React app use
only the records of the scopes of the operation. The UI shows an action
of an operation that only a membership gives if the record is in a scope
of the operation: the data access of each entity of the scope gives the
operations of the memberships of the user on some records
(`permissions`).
"""

from dataclasses import dataclass

from appgen.bindings.shared.auth import PathStep, path_steps
from appgen.dsl.access import membership_roles, scope_entities
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel

RECORD_KINDS = frozenset({"read", "update", "delete", "custom"})
"""The kinds of the operations on one record: a membership gives them in the scope of the record."""


@dataclass(frozen=True, slots=True)
class MemberPlan:
    """The memberships of the app, in TypeScript terms."""

    element_id: str
    entity: str
    """The membership entity, for example `Enrollment`."""
    user_key: str
    """The key of the relation to the user in a membership record, for example `personId`."""
    scope_key: str
    """The key of the relation to the scope record, for example `courseId`."""
    role_key: str
    """The key of the role field, for example `role`."""
    scope: str
    """The scope entity, for example `Course`."""
    roles: dict[str, list[str]]
    """The operations of each role, sorted, with `*` expanded."""
    role_ids: dict[str, str]
    """The element ID of each role."""
    paths: dict[str, tuple[PathStep, ...]]
    """The steps of the path of each entity of the scope to the scope entity. The scope entity
    has no step: its records are the scopes."""
    operation_entities: dict[str, str]
    """The entity of each operation of the roles."""
    record_operations: tuple[str, ...]
    """The operations of the roles on one record, sorted: a read, a change, a delete, or a
    custom operation."""

    @property
    def operations(self) -> list[str]:
        """The operations that a role of the memberships gives, sorted."""
        return sorted(self.operation_entities)

    def operations_of(self, entity: str) -> list[str]:
        """Return the operations of the roles on the records of an entity, sorted."""
        return sorted(name for name, owner in self.operation_entities.items() if owner == entity)


def member_plan(definition: AppDefinition) -> MemberPlan | None:
    """Return the memberships of the app, or None without `access.memberships`."""
    access = definition.access
    memberships = access.memberships if access is not None else None
    if memberships is None:
        return None
    scoped = scope_entities(definition)
    roles = membership_roles(definition)
    names = {name for ops in roles.values() for name in ops}
    operations = {name: definition.operations[name] for name in sorted(names)}
    relations = definition.entities[memberships.entity].relations
    return MemberPlan(
        element_id=memberships.id,
        entity=memberships.entity,
        user_key=camel(memberships.user) + "Id",
        scope_key=camel(memberships.scope) + "Id",
        role_key=camel(memberships.role_field),
        scope=relations[memberships.scope].target,
        roles=roles,
        role_ids={name: role.id for name, role in memberships.roles.items()},
        paths={
            name: path_steps(definition, name, path) if path else ()
            for name, path in scoped.items()
        },
        operation_entities={name: op.entity for name, op in operations.items()},
        record_operations=tuple(name for name, op in operations.items() if op.kind in RECORD_KINDS),
    )
