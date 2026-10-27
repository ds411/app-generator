"""The records of the guests in the FastAPI app (ADR 0050).

`app/core/guests.py` gives the guest tokens, the access check and the
scope of the guest operations, and the move of the records of a guest
to a signed-in user. Each entity of `auth.guests` has the column
`guest_id`: the guest of a record, until the move. The repositories of
these entities filter the records of a guest by this column.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from appgen.dsl.model import AppDefinition
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyOperation, PyRelation

COLUMN = "guest_id"
"""The column of the guest of a record."""
OPERATION_IDS = ("start_guest_session", "move_guest_records")
"""The operation IDs of the endpoints of the guests: the guest token, and the move."""


@dataclass(slots=True)
class PyGuestEntity:
    """An entity whose records a guest can own, and its owner relation to the user entity."""

    entity: PyEntity
    owner: PyRelation


@dataclass(slots=True)
class PyGuests:
    """The guests of the app: the entities of their records, and the guest operations."""

    id: str
    entities: list[PyGuestEntity]
    operations: list[str]
    """The operations that a guest may call, sorted by name."""
    days: int
    """The time after which a guest token ends, in days."""
    tested: list[PyGuestTest] = field(default_factory=list["PyGuestTest"])
    """The generated tests: one for each entity with a create and a list guest operation."""


@dataclass(slots=True)
class PyGuestTest:
    """The generated test of the records of a guest of one entity."""

    entity: PyGuestEntity
    create: PyOperation
    list: PyOperation
    read: PyOperation | None = None
    """The read guest operation of the entity, if there is one."""


def python_guests(definition: AppDefinition, entities: dict[str, PyEntity]) -> PyGuests | None:
    """Return the guests of the app, and mark the guest entities and operations.

    Return None without `auth.guests`. Raise GenerationError if an entity of
    the guests has a member with the name of the column of the guest, or if
    an operation has the operation ID of an endpoint of the guests.
    """
    auth = definition.auth
    guests = auth.guests if auth is not None else None
    if guests is None:
        return None
    for name in OPERATION_IDS:
        if name in definition.operations:
            raise GenerationError(
                f"The operation '{name}' has the operation ID of an endpoint of the guests. "
                "Rename the operation."
            )
    found: list[PyGuestEntity] = []
    for name, owner in guests.entities.items():
        entity = entities[name]
        attrs = {f.attr for f in entity.fields} | {c.attr for c in entity.computed}
        attrs |= {r.attr for r in entity.relations} | {r.fk_attr for r in entity.relations}
        if COLUMN in attrs:
            raise GenerationError(
                f"The entity '{name}' has a member '{COLUMN}', which is the column of the guest "
                "of a record. Rename the member."
            )
        relation = next(r for r in entity.relations if r.name == owner)
        entity.guest_owner = relation
        entity.scoped = True
        found.append(PyGuestEntity(entity=entity, owner=relation))
    for entity in entities.values():
        for op in entity.operations:
            op.guest = op.name in guests.operations
    result = PyGuests(
        id=guests.id,
        entities=found,
        operations=sorted(guests.operations),
        days=guests.token_days,
    )
    for item in found:
        ops = {op.kind: op for op in item.entity.operations if op.guest}
        create, listing = ops.get("create"), ops.get("list")
        if create is not None and listing is not None:
            test = PyGuestTest(entity=item, create=create, list=listing, read=ops.get("read"))
            result.tested.append(test)
    return result
