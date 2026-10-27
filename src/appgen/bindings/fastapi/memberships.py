"""The roles of the memberships in the FastAPI app (ADR 0048).

A membership record gives its user a role in one record of the scope
entity, for example a course. The role gives operations on the records
of the scope: the scope record, and the records whose path ends at it.
`app/core/access.py` has the operations of each role (`MEMBER_ROLES`) and
reads the scopes of the user of a request. The repositories of the
entities of the scope filter the records by the path (`in_scopes`).

The generated test stores a user with two roles in two scope records,
and a third scope record without a membership. An operation that one
role gives and the other does not gives 200 (or 204) in the first scope,
403 in the second, and 404 in the third.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import permutations
from typing import TYPE_CHECKING

from appgen.bindings.fastapi.pysource import LINE_LENGTH, call
from appgen.dsl.access import ALL, Role, scope_entities
from appgen.dsl.model import AppDefinition

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyField, PyOperation, PyRelation

RECORD_KINDS = ("update", "read", "delete")
"""The kinds of the operation of the test: an operation on one record, in this order."""


@dataclass(slots=True)
class PyMemberTest:
    """The generated test of a user with two roles in two scope records."""

    entity: PyEntity
    """The entity of the records of the test, an entity of the scope."""
    app_role: str
    """The role of the user in `access.roles`: it gives none of the operations of the test."""
    allowed: str
    """The role of the memberships that gives `operation`."""
    other: str
    """The role of the memberships that does not give `operation`."""
    operation: PyOperation
    """An operation on one record that `allowed` gives and `other` does not."""
    listing: PyOperation | None = None
    """The list operation of the entity, if `allowed` or `other` gives it."""
    listed: list[str] = field(default_factory=list[str])
    """The roles that give `listing`: the list has the records of their scopes."""
    creating: PyOperation | None = None
    """The create operation of the entity, if `allowed` gives it and `other` does not."""
    denied: PyOperation | None = None
    """An operation on one record that no role of the user gives."""

    @property
    def scope_entity(self) -> bool:
        """True if the records of the test are the scope records."""
        return self.entity.scope_path is not None and not self.entity.scope_path.steps

    def records(self) -> str:
        """Return the statement of the test that stores a record in each scope (indent 4)."""
        if self.scope_entity:
            return "records = scopes"
        name = self.entity.snake
        element = f"await make_{name}(session, **await _{name}_in(session, scope))"
        one_line = f"records = [{element} for scope in scopes]"
        if 4 + len(one_line) <= LINE_LENGTH:
            return one_line
        if 8 + len(f"{element} for scope in scopes") <= LINE_LENGTH:
            return f"records = [\n        {element} for scope in scopes\n    ]"
        element = call(
            "await ", f"make_{name}", ["session", f"**await _{name}_in(session, scope)"], 8
        )
        return f"records = [\n        {element}\n        for scope in scopes\n    ]"


@dataclass(slots=True)
class PyMemberships:
    """The memberships of the app: the entity, its relations, and the operations of each role."""

    id: str
    entity: PyEntity
    """The membership entity."""
    user: PyRelation
    """The many-to-one relation to the user entity."""
    scope: PyRelation
    """The many-to-one relation to the scope entity."""
    scope_entity: PyEntity
    role: PyField
    """The enum field of the membership entity with the role of the member."""
    roles: dict[str, list[str]]
    """The operations of each role, by value of the role field. `*` gives all operations of
    the entities of the scope."""
    role_ids: dict[str, str]
    """The element ID of each role."""
    entities: list[str]
    """The entities of the scope: the scope entity first, then the entities of `paths`."""
    tests: list[PyMemberTest] = field(default_factory=list[PyMemberTest])
    """The generated tests: one for each entity of the scope with an operation that suits."""

    @property
    def operations(self) -> list[str]:
        """The operations that a role of the memberships gives, sorted by name."""
        return sorted({name for names in self.roles.values() for name in names})


def python_memberships(
    definition: AppDefinition, entities: dict[str, PyEntity]
) -> PyMemberships | None:
    """Return the memberships of the app, or None without `access.memberships`."""
    access = definition.access
    memberships = access.memberships if access is not None else None
    if access is None or memberships is None:
        return None
    scoped = scope_entities(definition)
    entity = entities[memberships.entity]
    relations = {r.name: r for r in entity.relations}
    user, scope = relations[memberships.user], relations[memberships.scope]
    role = next(f for f in entity.fields if f.name == memberships.role_field)
    scope_ops = [
        name
        for name, op in definition.operations.items()
        if op.entity in scoped and op.kind != "query"
    ]
    roles = {
        name: sorted(scope_ops if ALL in r.operations else r.operations)
        for name, r in memberships.roles.items()
    }
    found = PyMemberships(
        id=memberships.id,
        entity=entity,
        user=user,
        scope=scope,
        scope_entity=entities[scope.target],
        role=role,
        roles=roles,
        role_ids={name: r.id for name, r in memberships.roles.items()},
        entities=list(scoped),
    )
    found.tests = _member_tests(definition, entities, found)
    return found


def _member_tests(
    definition: AppDefinition, entities: dict[str, PyEntity], memberships: PyMemberships
) -> list[PyMemberTest]:
    """Return the tests of two roles in two scopes: one for each entity of the scope that suits.

    A test needs an operation on one record that a role gives and another
    role does not, and an app role that does not give the operation. The
    list is in the test if the app role does not give it.
    """
    access = definition.access
    if access is None:
        return []
    roles = memberships.roles
    found: list[PyMemberTest] = []
    for name in memberships.entities:
        entity = entities[name]
        ops = {op.kind: op for op in entity.operations if op.protected and op.kind != "custom"}
        test = _entity_test(access.roles, roles, entity, ops)
        if test is not None:
            found.append(test)
    return found


def _entity_test(
    app_roles: Mapping[str, Role],
    roles: dict[str, list[str]],
    entity: PyEntity,
    ops: dict[str, PyOperation],
) -> PyMemberTest | None:
    """Return the test of an entity of the scope, or None if no operation suits."""
    for kind in RECORD_KINDS:
        op = ops.get(kind)
        if op is None:
            continue
        for allowed, other in permutations(roles, 2):
            if op.name not in roles[allowed] or op.name in roles[other]:
                continue
            app_role = next(
                (r for r, role in app_roles.items() if not role.allows_operation(op.name)), None
            )
            if app_role is None:
                continue
            app = app_roles[app_role]
            given = {*roles[allowed], *roles[other]}
            listing = ops.get("list")
            if listing is not None and app.allows_operation(listing.name):
                listing = None
            listed = [r for r in (allowed, other) if listing and listing.name in roles[r]]
            create = ops.get("create")
            steps = entity.scope_path.steps if entity.scope_path else []
            creating = (
                create
                if create is not None
                and steps
                and create.name in roles[allowed]
                and create.name not in roles[other]
                and not app.allows_operation(create.name)
                else None
            )
            denied = next(
                (
                    ops[k]
                    for k in RECORD_KINDS
                    if k in ops
                    and ops[k].name not in given
                    and not app.allows_operation(ops[k].name)
                ),
                None,
            )
            return PyMemberTest(
                entity=entity,
                app_role=app_role,
                allowed=allowed,
                other=other,
                operation=op,
                listing=listing if listed else None,
                listed=listed,
                creating=creating,
                denied=denied,
            )
    return None
