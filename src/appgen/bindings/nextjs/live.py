"""The live updates of the records in the Next.js app (ADR 0051)."""

from dataclasses import dataclass, field

from appgen.bindings.nextjs.db import Table
from appgen.bindings.shared.auth import PathStep, path_steps
from appgen.bindings.shared.typescript import ts_value
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel


@dataclass(frozen=True, slots=True)
class TsReadRule:
    """The record rule of a role for the reads of a live entity (ADR 0025)."""

    owner: bool
    where: dict[str, list[str | int | bool]]
    """The values of each field, by the key of the field in the record."""

    def entry(self) -> str:
        """Return the rule as a TypeScript object, for example `{ owner: true }`."""
        parts = ["owner: true"] if self.owner else []
        if self.where:
            items = ", ".join(f"{key}: {ts_value(values)}" for key, values in self.where.items())
            parts.append(f"where: {{ {items} }}")
        return f"{{ {', '.join(parts)} }}" if parts else "{}"


@dataclass(frozen=True, slots=True)
class TsLiveEntity:
    """A live entity in TypeScript terms."""

    name: str
    id: str
    """The element ID of `live`, for the traces."""
    readers: tuple[str, ...]
    """The list and the read operations: a role that may call one gets the events."""
    public: bool
    """True if a list or a read operation is public: all clients get the events."""
    rules: dict[str, TsReadRule] = field(default_factory=dict[str, TsReadRule])
    """The record rules of the reads, by role."""
    owner_path: tuple[str, ...] = ()
    """The steps of the owner path (`PathStep`), if a rule of the reads has `owner`."""
    tables: tuple[str, ...] = ()
    """The tables that the steps of the owner path use, sorted."""


def live_entities(definition: AppDefinition, tables: dict[str, Table]) -> list[TsLiveEntity]:
    """Return the live entities of a definition, in the order of the definition."""
    public_ops = set(definition.auth.public_operations) if definition.auth else set[str]()
    found: list[TsLiveEntity] = []
    for name, entity in definition.entities.items():
        if entity.live is None:
            continue
        readers = tuple(
            op_name
            for op_name, op in definition.operations.items()
            if op.entity == name and op.kind in ("list", "read")
        )
        rules: dict[str, TsReadRule] = {}
        owner = None
        if definition.access is not None:
            for role_name, role in definition.access.roles.items():
                rule = role.records.get(name)
                if rule is None or "read" not in rule.operations:
                    continue
                where = {camel(k): v for k, v in rule.conditions().items()}
                rules[role_name] = TsReadRule(rule.owner is not None, where)
                owner = rule.owner or owner
        steps, used = (
            (owner_steps(path_steps(definition, name, owner), tables)) if owner else ((), ())
        )
        found.append(
            TsLiveEntity(
                name,
                entity.live.id,
                readers,
                any(op in public_ops for op in readers),
                rules,
                steps,
                used,
            )
        )
    return found


def owner_steps(
    steps: tuple[PathStep, ...], tables: dict[str, Table]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the `PathStep` of each step of an owner path, and the tables that they use."""
    used: set[str] = set()
    found: list[str] = []
    for step in steps:
        table = tables[step.entity]
        if step.many:
            item = next(i for i in table.lists if i.element_id == step.element_id)
            used.add(item.join_const)
            join = item.join_const
            found.append(f"[{join}, {join}.{item.owner_key}, {join}.{item.target_key}]")
        else:
            used.add(table.const)
            found.append(f"[{table.const}, {table.const}.id, {table.const}.{step.key}]")
    return tuple(found), tuple(sorted(used))
