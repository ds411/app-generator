"""Python helpers for the templates of the React binding.

The generator adds each function of `HELPERS` to the template globals,
and the values of `context()` to the context of all templates. The
helpers are deterministic: they read only the definition.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from appgen.bindings.react.mock_data import mock_data
from appgen.dsl.model import AppDefinition, Entity, Field, Relation
from appgen.gen.naming import camel, pascal, words

_PARAM = re.compile(r"\{([a-z][a-z0-9_]*)\}")

_TS_TYPES = {
    "string": "string",
    "text": "string",
    "email": "string",
    "url": "string",
    "uuid": "string",
    "date": "string",
    "datetime": "string",
    "integer": "number",
    "decimal": "number",
    "boolean": "boolean",
    "json": "unknown",
}


def route_path(path: str) -> str:
    """Return the React Router path of a page path: `/projects/{id}` gives `/projects/:id`."""
    return _PARAM.sub(lambda match: ":" + match.group(1), path)


def route_params(path: str) -> list[str]:
    """Return the names of the path parameters of a page path, in order."""
    return _PARAM.findall(path)


def label(name: str) -> str:
    """Return a display label for a name: `due_date` gives `Due date`."""
    text = " ".join(words(name))
    return text[:1].upper() + text[1:]


def ts_value(value: Any, indent: int | None = None) -> str:
    """Return a TypeScript literal for a JSON value, on one line or with an indent."""
    return json.dumps(value, ensure_ascii=False, indent=indent)


def enum_type(entity_name: str, field_name: str) -> str:
    """Return the name of the TypeScript type of an enum field, for example `TaskStatus`."""
    return pascal(entity_name) + pascal(field_name)


def enum_values_name(entity_name: str, field_name: str) -> str:
    """Return the name of the constant with the values of an enum field."""
    return camel(entity_name) + pascal(field_name) + "Values"


@dataclass(frozen=True, slots=True)
class Member:
    """A key of the TypeScript type of an entity: a field or a stored relation."""

    name: str
    """The name in the definition, for example `due_date` or `project`."""
    key: str
    """The key in TypeScript, for example `dueDate` or `projectId`."""
    element_id: str
    ts_type: str
    """The TypeScript type without `| null`."""
    nullable: bool
    input_required: bool
    """True if the create input must have the key."""
    default: Any
    """The value of the key when the create input does not have it."""
    field: Field | None = None
    relation: Relation | None = None


def members(entity_name: str, entity: Entity) -> list[Member]:
    """Return the keys of the TypeScript type of an entity, in source order.

    Fields come first, then the relations that the record stores: the ID
    of the target for `many_to_one` and `one_to_one`, and the list of IDs
    for `many_to_many`. A `one_to_many` relation is not stored: the target
    stores the other side.
    """
    result: list[Member] = []
    for name, field in entity.fields.items():
        ts_type = enum_type(entity_name, name) if field.type == "enum" else _TS_TYPES[field.type]
        has_default = field.default is not None
        result.append(
            Member(
                name=name,
                key=camel(name),
                element_id=field.id,
                ts_type=ts_type,
                nullable=not field.required and not has_default and field.type != "boolean",
                input_required=field.required and not has_default,
                default=field.default
                if has_default
                else (False if field.type == "boolean" else None),
                field=field,
            )
        )
    for name, relation in entity.relations.items():
        if relation.kind in ("many_to_one", "one_to_one"):
            result.append(
                Member(
                    name=name,
                    key=camel(name) + "Id",
                    element_id=relation.id,
                    ts_type="string",
                    nullable=not relation.required,
                    input_required=relation.required,
                    default=None,
                    relation=relation,
                )
            )
        elif relation.kind == "many_to_many":
            result.append(
                Member(
                    name=name,
                    key=camel(name),
                    element_id=relation.id,
                    ts_type="string[]",
                    nullable=False,
                    input_required=False,
                    default=[],
                    relation=relation,
                )
            )
    return result


def operations_of(definition: AppDefinition, entity_name: str) -> list[tuple[str, Any]]:
    """Return the operations on an entity, in source order, as (name, operation) pairs."""
    return [(n, op) for n, op in definition.operations.items() if op.entity == entity_name]


def inverse_lists(definition: AppDefinition, entity_name: str) -> list[tuple[str, str, Relation]]:
    """Return the `one_to_many` relations whose records are of this entity.

    Each entry is (owner entity, relation name, relation). The data access
    of this entity lists the records of one owner with the foreign key of
    the inverse relation.
    """
    return [
        (owner_name, name, relation)
        for owner_name, owner in definition.entities.items()
        for name, relation in owner.relations.items()
        if relation.kind == "one_to_many" and relation.target == entity_name
    ]


def mock_records(definition: AppDefinition) -> dict[str, list[dict[str, Any]]]:
    """Return the mock records of each entity, with the keys of the TypeScript types."""
    data = mock_data(definition)
    result: dict[str, list[dict[str, Any]]] = {}
    for entity_name, entity in definition.entities.items():
        keys = {m.name: m.key for m in members(entity_name, entity)}
        result[entity_name] = [
            {"id": record["id"]} | {keys[k]: v for k, v in record.items() if k in keys}
            for record in data[entity_name]
        ]
    return result


def context(definition: AppDefinition) -> dict[str, Any]:
    """Return the values that the binding adds to the context of all templates."""
    return {"mock": mock_records(definition)}


HELPERS: dict[str, Callable[..., Any]] = {
    "route_path": route_path,
    "route_params": route_params,
    "label": label,
    "ts_value": ts_value,
    "enum_type": enum_type,
    "enum_values_name": enum_values_name,
    "members": members,
    "operations_of": operations_of,
    "inverse_lists": inverse_lists,
}
