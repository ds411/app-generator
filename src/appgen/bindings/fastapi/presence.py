"""The other users on a record page in the FastAPI app (ADR 0052).

The slice of an entity with a page with `presence` has `presence.py`:
the endpoints that note the signed-in user on a record, and that end it.
`app/core/live.py` keeps the users on each record in the broker of the
live updates, and sends their changes through the stream (ADR 0051).
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from appgen.bindings.fastapi.pysource import from_import, import_block
from appgen.bindings.shared.presence import presence_entities
from appgen.dsl.model import AppDefinition
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyOperation


@dataclass(slots=True)
class PyPresence:
    """The pages with `presence` of an entity: the endpoints of the users on its records."""

    entity: PyEntity
    read: PyOperation
    """The read operation of the entity: the endpoints need its permission."""
    user_label: str
    """The attribute of the user model that names a user."""
    ids: list[str] = field(default_factory=list[str])
    """The element IDs of the pages."""

    @property
    def id(self) -> str:
        """The element ID of the first page, for the traces of the file."""
        return self.ids[0]

    @property
    def scope(self) -> bool:
        """True if the record rules of a read apply to the endpoints (ADR 0025)."""
        return self.read.scope_action is not None and self.entity.scoped

    @property
    def operations(self) -> dict[str, str]:
        """The operation IDs of the endpoints, by kind."""
        s = self.entity.snake
        return {"here": f"update_{s}_presence", "leave": f"delete_{s}_presence"}

    @property
    def guarded(self) -> list[str]:
        """The operation IDs that need the permission of the read operation."""
        return list(self.operations.values())

    def doc(self) -> str:
        """Return the docstring of the module of the endpoints."""
        e = self.entity
        rules = ", and its record rules" if self.scope else ""
        return (
            f'"""The other users on the pages of the records of {e.name} (ADR 0052).\n\n'
            "The page of a record notes its signed-in user each few seconds, and when\n"
            "the user starts or stops to type. The endpoints need the permission of\n"
            f'`{self.read.name}`{rules}.\n"""'
        )

    def imports(self) -> str:
        """Return the import block of the module of the endpoints."""
        e = self.entity
        fastapi = {"APIRouter", "Request"}
        lines = {
            "from uuid import UUID",
            "from app.core.auth import CurrentUser",
            "from app.core.db import SessionDep",
            "from app.core.errors import problem_responses",
            from_import("app.core.live", {"Broker", "Presence", "PresenceInput"}),
            f"from app.features.{e.slice} import repository",
        }
        access: set[str] = set()
        if self.read.protected and e.guard == "check_access":
            access.add("check_access")
        if self.scope:
            access |= {"RecordScope", "scope_of"}
            lines.add("from typing import Annotated")
        if access:
            fastapi.add("Depends")
            lines.add(from_import("app.core.access", access))
        lines.add(from_import("fastapi", fastapi))
        return import_block(lines)


def python_presences(
    definition: AppDefinition, entities: dict[str, PyEntity], user_label: str | None
) -> None:
    """Give the entities with a page with `presence` their endpoints.

    Raise GenerationError if an operation has the operation ID of an endpoint.
    """
    for name, plans in presence_entities(definition).items():
        entity = entities[name]
        read = next(op for op in entity.operations if op.name == plans[0].read)
        assert user_label is not None
        presence = PyPresence(entity, read, user_label, [plan.page_id for plan in plans])
        for operation_id in presence.operations.values():
            if operation_id in definition.operations:
                raise GenerationError(
                    f"The endpoint of the users on the records of '{name}' has the operation "
                    f"ID '{operation_id}' of an operation. Rename the operation."
                )
        entity.presence = presence
