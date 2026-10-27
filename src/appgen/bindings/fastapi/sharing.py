"""The secret links of the records in the FastAPI app (ADR 0049).

`app/core/sharing.py` has the table `share_links` and the functions of
the links. The slice of an entity with a page with `share` has
`share.py`: the endpoints that read, make, and revoke the link of a
record, and the public endpoint that reads the record of a token, with
the related records that the detail view of the page shows.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from appgen.bindings.fastapi.pysource import LINE_LENGTH, call, from_import, import_block
from appgen.bindings.shared.sharing import share_plans
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import snake
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyOperation

TABLE = "share_links"
"""The table of the links."""


@dataclass(slots=True)
class PyRelatedStep:
    """The related records of one entity that a shared page shows."""

    name: str
    """The key of the records in `related`: the snake-case name of the entity."""
    target: PyEntity
    keys: list[tuple[str | None, str]] = field(default_factory=list[tuple[str | None, str]])
    """The step whose records have the IDs (None for the shared record), and the attribute."""


@dataclass(slots=True)
class PyShare:
    """The page with `share` of an entity: the endpoints of the links of its records."""

    id: str
    """The element ID of the page."""
    entity: PyEntity
    update: PyOperation
    """The update operation of the entity: the links need its permission."""
    related: list[PyRelatedStep] = field(default_factory=list[PyRelatedStep])
    tested: tuple[str, str] | None = None
    """A related record that the tests find: the step, and the required foreign key of the
    shared record that has its ID."""
    access: bool = False
    """True if the app has roles: the update operation gives the permission of the links."""

    @property
    def scope(self) -> bool:
        """True if the record rules of a change apply to the links (ADR 0025)."""
        return self.update.scope_action is not None and self.entity.scoped

    @property
    def operations(self) -> dict[str, str]:
        """The operation IDs of the endpoints of the links, by kind."""
        s = self.entity.snake
        return {
            "read": f"read_{s}_share_link",
            "create": f"create_{s}_share_link",
            "revoke": f"revoke_{s}_share_link",
            "shared": f"read_shared_{s}",
        }

    @property
    def guarded(self) -> list[str]:
        """The operation IDs that need the permission of the update operation."""
        ops = self.operations
        return [ops["read"], ops["create"], ops["revoke"]]

    @property
    def shared_path(self) -> str:
        """The path of the public endpoint, for example `/shared/lessons/{token}`."""
        return f"/shared{self.entity.path}/{{token}}"

    def doc(self) -> str:
        """Return the docstring of the module of the endpoints."""
        e = self.entity
        rules = ", and its record rules of a change" if self.scope else ""
        return (
            f'"""The secret links of the records of {e.name} (ADR 0049).\n\n'
            f"The link of a record needs the permission of `{self.update.name}`{rules}.\n"
            'The record of a token is public.\n"""'
        )

    def imports(self) -> str:
        """Return the import block of the module of the endpoints."""
        e = self.entity
        core = {"ShareLinkCreated", "ShareLinkState", "link_state", "make_link"}
        core |= {"not_shared", "revoke_link", "shared_id"}
        if self.related:
            core |= {"RelatedStep", "related_records"}
        fastapi = {"APIRouter"}
        lines = {
            "from uuid import UUID",
            "from pydantic import BaseModel",
            "from app.core.db import SessionDep",
            "from app.core.errors import problem_responses",
            from_import("app.core.sharing", core),
            f"from app.features.{e.slice}.models import {e.name}",
            f"from app.features.{e.slice}.schemas import {e.name}Read",
        }
        if self.update.protected or self.scope or e.translations_query:
            fastapi.add("Depends")
        if self.update.protected:
            lines.add(from_import(f"app.core.{e.guard_module}", {e.guard}))
        if self.scope:
            lines.add("from typing import Annotated")
            lines.add(from_import("app.core.access", {"RecordScope", "scope_of"}))
        lines.add(f"from app.features.{e.slice} import repository")
        if e.translations_query:
            lines.add("from app.core.i18n import translations_query")
        targets: dict[str, set[str]] = {}
        models: dict[str, set[str]] = {}
        for step in self.related:
            t = step.target
            if t.name != e.name:
                targets.setdefault(t.slice, set()).add(f"{t.name}Read")
                models.setdefault(t.slice, set()).add(t.name)
        for slice_name, names in targets.items():
            lines.add(from_import(f"app.features.{slice_name}.schemas", names))
        for slice_name, names in models.items():
            lines.add(from_import(f"app.features.{slice_name}.models", names))
        lines.add(from_import("fastapi", fastapi))
        return import_block(lines)

    def related_code(self) -> str:
        """Return the constant with the steps of the related records."""
        items: list[str] = []
        for step in self.related:
            keys = ", ".join(
                f"({'None' if source is None else repr(source)}, {attr!r})".replace("'", '"')
                for source, attr in step.keys
            )
            keys = f"({keys},)" if len(step.keys) == 1 else f"({keys})"
            items.append(call("", "RelatedStep", [f'"{step.name}"', step.target.name, keys], 4))
        joined = f"{items[0]}," if len(items) == 1 else ", ".join(items)
        one_line = f"RELATED = ({joined})"
        if len(one_line) <= LINE_LENGTH and "\n" not in one_line:
            return one_line
        inner = "".join(f"    {item},\n" for item in items)
        return f"RELATED = (\n{inner})"

    def related_fields(self) -> list[str]:
        """Return the fields of the model of the related records."""
        return [f"{step.name}: list[{step.target.name}Read]" for step in self.related]

    def related_values(self) -> list[str]:
        """Return the arguments of the model of the related records."""
        return [
            f"{step.name}=[{step.target.name}Read.model_validate(item) "
            f'for item in related["{step.name}"]]'
            for step in self.related
        ]


def python_shares(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Give the entities with a page with `share` their links.

    Raise GenerationError if an entity has the table of the links, or if an
    operation has the operation ID of an endpoint of the links.
    """
    plans = share_plans(definition)
    for entity in entities.values() if plans else ():
        if entity.table == TABLE:
            raise GenerationError(
                f"The entity '{entity.name}' has the table '{TABLE}' of the secret links. "
                "Give it another table with x-fastapi-table."
            )
    for name, plan in plans.items():
        entity = entities[name]
        update = next(op for op in entity.operations if op.name == plan.update)
        share = PyShare(
            id=plan.page_id, entity=entity, update=update, access=definition.access is not None
        )
        for stage in plan.related:
            for step in stage:
                py_step = PyRelatedStep(snake(step.entity), entities[step.entity])
                for key in step.keys:
                    holder = entities[key.entity]
                    relation = next(r for r in holder.relations if r.name == key.relation)
                    attr = relation.fk_attr if relation.side == "fk" else relation.attr
                    source = None if key.source is None else snake(key.entity)
                    py_step.keys.append((source, attr or relation.attr))
                    if source is None and relation.side == "fk" and relation.required:
                        share.tested = share.tested or (py_step.name, relation.fk_attr or "")
                share.related.append(py_step)
        for operation_id in share.operations.values():
            if operation_id in definition.operations:
                raise GenerationError(
                    f"The endpoint of the links of '{name}' has the operation ID "
                    f"'{operation_id}' of an operation. Rename the operation."
                )
        entity.share = share
