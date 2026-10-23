"""TypeScript helpers that the Next.js and the React bindings share.

The entity slices of both apps have the same types and the same names,
so that the shared UI templates work in both apps. The functions are
deterministic: they read only the definition.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from appgen.dsl.model import AppDefinition, Entity, Field, Relation
from appgen.gen.naming import camel, pascal, words

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


def label(name: str) -> str:
    """Return a display label for a name: `due_date` gives `Due date`."""
    text = " ".join(words(name))
    return text[:1].upper() + text[1:]


def to_json(value: Any) -> str:
    """Return a value as JSON with an indent of two spaces, as the Node.js tools write it."""
    return json.dumps(value, indent=2, ensure_ascii=False)


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


def param_type(param: Field) -> str:
    """Return the TypeScript type of an operation parameter, without `| null`."""
    if param.type == "enum":
        return " | ".join(f'"{value}"' for value in param.values or [])
    return _TS_TYPES[param.type]


def zod_type(field: Field, enum_values: str | None = None) -> str:
    """Return the zod schema of a field value, with its rules, without `optional`.

    `enum_values` is the name of the constant with the values of an enum
    field. Without it, the schema lists the values.
    """
    match field.type:
        case "email":
            code = "z.email()"
        case "url":
            code = "z.url()"
        case "uuid":
            code = "z.uuid()"
        case "date":
            code = "z.iso.date()"
        case "datetime":
            code = "z.iso.datetime({ offset: true })"
        case "integer":
            code = "z.int32()"
        case "decimal":
            code = "z.number()"
        case "boolean":
            code = "z.boolean()"
        case "enum":
            code = f"z.enum({enum_values or ts_value(field.values or [])})"
        case "json":
            code = "z.json()"
        case _:
            code = "z.string()"
    if field.type in ("string", "text", "email", "url"):
        min_length = field.min_length
        if min_length is None and field.required:
            min_length = 1
        if min_length:
            code += f".min({min_length})"
        if field.max_length is not None:
            code += f".max({field.max_length})"
        if field.pattern is not None:
            code += f".regex(new RegExp({ts_value(field.pattern)}))"
    if field.type in ("integer", "decimal"):
        for rule in ("min", "max"):
            value = getattr(field, rule)
            if value is not None:
                code += f".{rule}({_number(value)})"
    return code


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def zod_schema(entity_name: str, member: Member) -> str:
    """Return the zod schema of a key of the create input of an entity."""
    if member.field is not None:
        enum_values = (
            enum_values_name(entity_name, member.name) if member.field.type == "enum" else None
        )
        code = zod_type(member.field, enum_values)
    elif member.ts_type == "string[]":
        code = "z.array(z.uuid())"
    else:
        code = "z.uuid()"
    if member.nullable:
        code += ".nullable()"
    if not member.input_required:
        code += ".optional()"
    return code


def param_schema(param: Field) -> str:
    """Return the zod schema of a parameter of a custom operation."""
    code = zod_type(param)
    if not param.required:
        code += ".nullish()"
    return code


HELPERS: dict[str, Callable[..., Any]] = {
    "label": label,
    "ts_value": ts_value,
    "enum_type": enum_type,
    "enum_values_name": enum_values_name,
    "members": members,
    "operations_of": operations_of,
    "inverse_lists": inverse_lists,
    "param_type": param_type,
    "zod_schema": zod_schema,
    "param_schema": param_schema,
}
"""The template globals that the shared entity templates use."""
