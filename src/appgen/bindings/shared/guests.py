"""The guests of the front ends (ADR 0050): the records of a visitor without a sign-in.

A guest calls the guest operations of `auth.guests` on its own records.
The table of the permissions (`@/shared/lib/permissions`) has the guest
operations and the entities of the guests. The Next.js app keeps a guest
session in a signed cookie, and the column `guest_id` of each entity of
the guests holds the guest of a record. The React app with the FastAPI app
keeps the guest token of the API. The React app with mock data keeps a
guest ID and the records of the guest for the tab, in the session
storage. At the sign-in and at the sign-up, the records of the guest move to
the user. The record rules of each entity of the guests (`record_rules`)
have the key of its owner relation.
"""

from dataclasses import dataclass

from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel
from appgen.gen.render import GenerationError

GUEST_KEY = "guestId"
"""The key of the guest of a record: the column `guest_id` in Next.js, a key of a mock record."""


@dataclass(frozen=True, slots=True)
class GuestEntity:
    """An entity whose records a guest can own, in TypeScript terms."""

    entity: str
    """The entity, for example `CartItem`."""
    owner_key: str
    """The key of the owner relation in the record, for example `customerId`."""


@dataclass(frozen=True, slots=True)
class GuestPlan:
    """The guests of the app, in TypeScript terms."""

    element_id: str
    entities: tuple[GuestEntity, ...]
    """The entities of the guests, in the order of `auth.guests.entities`."""
    operations: tuple[str, ...]
    """The operations that a guest may call, sorted."""
    days: int
    """The time after which a guest session ends, in days."""

    @property
    def names(self) -> list[str]:
        """The names of the entities of the guests."""
        return [item.entity for item in self.entities]


def guest_plan(definition: AppDefinition) -> GuestPlan | None:
    """Return the guests of the app, or None without `auth.guests`.

    Raise GenerationError if an entity of the guests has a member with the
    key of the guest of a record.
    """
    auth = definition.auth
    guests = auth.guests if auth is not None else None
    if guests is None:
        return None
    for name in guests.entities:
        entity = definition.entities[name]
        keys = {camel(f) for f in entity.fields} | {camel(r) for r in entity.relations}
        keys |= {camel(r) + "Id" for r in entity.relations}
        if GUEST_KEY in keys:
            raise GenerationError(
                f"The entity '{name}' has a member with the key '{GUEST_KEY}', which is the key "
                "of the guest of a record. Rename the member."
            )
    return GuestPlan(
        element_id=guests.id,
        entities=tuple(
            GuestEntity(entity=name, owner_key=camel(owner) + "Id")
            for name, owner in guests.entities.items()
        ),
        operations=tuple(sorted(guests.operations)),
        days=guests.token_days,
    )
