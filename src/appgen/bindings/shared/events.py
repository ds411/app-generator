"""The events of the entities for the Next.js and the React apps (ADR 0031).

The repository of the Next.js app and the mock store of the React app run
the operation of an event after a change of a record. The templates get
one `TsEvent` for each event and for each transition with `run`, and
render them in the options of the data access of the entity.
"""

import json
from dataclasses import dataclass
from typing import Literal

from appgen.dsl.events import EVENT_NAMES
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel, kebab

type EventKind = Literal["created", "changed", "deleted", "transition"]


@dataclass(frozen=True, slots=True)
class TsEvent:
    """An event of an entity, or a transition of a workflow with `run`."""

    kind: EventKind
    element_id: str
    """The element of the event or of the transition, for the trace."""
    operation: str
    """The custom operation of the event, for example `notify_owner`."""
    keys: tuple[str, ...] = ()
    """Only for `changed`: the keys of the fields that the event watches."""
    field: str | None = None
    """Only for a transition: the key of the field of the workflow."""
    before: tuple[str, ...] = ()
    """Only for a transition: the states before the change."""
    after: str | None = None
    """Only for a transition: the state after the change."""
    params: str | None = None
    """The params of the operation as a TypeScript object, or None without params."""

    @property
    def function(self) -> str:
        """The function of the operation in its extension file, for example `notifyOwner`."""
        return camel(self.operation)

    @property
    def module(self) -> str:
        """The extension file of the operation, for example `@/features/notify-owner/api/...`."""
        name = kebab(self.operation)
        return f"@/features/{name}/api/{name}.ext"

    @property
    def schema(self) -> str | None:
        """The zod schema of the params of the operation, or None without params."""
        return f"{self.function}ParamsSchema" if self.params is not None else None

    def call(self, parse: bool = True) -> str:
        """Return the TypeScript call of the operation with the record and the params.

        With `parse`, the zod schema of the params checks them.
        """
        if self.params is None:
            return f"{self.function}(record)"
        params = f"{self.schema}.parse({self.params})" if parse else self.params
        return f"{self.function}(record, {params})"


def ts_events(definition: AppDefinition, entity: str) -> list[TsEvent]:
    """Return the events of an entity: `created`, `changed`, `deleted`, then the transitions."""
    element = definition.entities[entity]
    found: list[TsEvent] = []
    for kind, event in sorted(element.events.items(), key=lambda item: EVENT_NAMES.index(item[0])):
        keys: tuple[str, ...] = ()
        if kind == "changed":
            # Without `fields`, a change of a stored field runs the event.
            keys = tuple(camel(name) for name in event.fields or element.stored_fields)
        found.append(
            TsEvent(
                kind=kind,
                element_id=event.id,
                operation=event.operation,
                keys=keys,
                params=_params(definition, event.operation),
            )
        )
    for workflow in definition.workflows.values():
        if workflow.entity != entity:
            continue
        for transition in workflow.transitions.values():
            if transition.run is None:
                continue
            found.append(
                TsEvent(
                    kind="transition",
                    element_id=transition.id,
                    operation=transition.run,
                    field=camel(workflow.field),
                    before=tuple(transition.from_),
                    after=transition.to,
                    params=_params(definition, transition.run),
                )
            )
    return found


def has_events(definition: AppDefinition) -> bool:
    """Return True if an entity has an event or a transition has `run`."""
    return any(entity.events for entity in definition.entities.values()) or any(
        t.run is not None for w in definition.workflows.values() for t in w.transitions.values()
    )


def _params(definition: AppDefinition, operation: str) -> str | None:
    """Return the params of an operation in an event: the default values, as in the FastAPI app.

    The validator rejects an operation of an event with a required param
    without a default value.
    """
    params = definition.operations[operation].params
    if not params:
        return None
    values = [
        f"{camel(name)}: {json.dumps(param.default, ensure_ascii=False)}"
        for name, param in params.items()
        if param.default is not None
    ]
    return "{ " + ", ".join(values) + " }" if values else "{}"
