"""TypeScript helpers that the Next.js and the React bindings share.

The entity slices of both apps have the same types and the same names,
so that the shared UI templates work in both apps. The functions are
deterministic: they read only the definition.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from appgen.bindings.shared.available import has_available
from appgen.bindings.shared.geo import has_points
from appgen.bindings.shared.integrations import ts_features
from appgen.bindings.shared.lines import line_items, lines_operations
from appgen.bindings.shared.notices import (
    email_notifications,
    has_mentions,
    has_notice_emails,
    has_notices,
    mention_link,
    mention_plans,
    mock_notify,
    notice_ids,
    notice_links,
    notice_plans,
    notice_summary,
    notice_texts,
)
from appgen.dsl.model import AppDefinition, Entity, Field, Operation, Relation
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
    "file": "FileValue",
    "image": "FileValue",
    "point": "GeoPoint",
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
    translations: Field | None = None
    """The translatable field whose values in each language the key has (ADR 0026)."""

    @property
    def is_file(self) -> bool:
        """True for the key of a file field (ADR 0027)."""
        return self.field is not None and self.field.is_file

    @property
    def input(self) -> bool:
        """True if the create and the change take the key.

        A file has an upload (ADR 0027), and the database gives the value of
        a field with a sequence.
        """
        return self.field is None or not (self.field.is_file or self.field.sequence is not None)


TRANSLATIONS_TYPE = "Partial<Record<string, string | null>>"
"""The TypeScript type of the values of a translatable field, by language code."""


def translations_key(name: str) -> str:
    """Return the key of the values of a translatable field, for example `titleTranslations`."""
    return camel(name) + "Translations"


def members(entity_name: str, entity: Entity) -> list[Member]:
    """Return the keys of the TypeScript type of an entity, in source order.

    The stored fields come first (a computed field is not a key), then
    the relations that the record stores: the ID of the target for
    `many_to_one` and `one_to_one`, and the list of IDs for
    `many_to_many`. A `one_to_many` relation is not stored: the target
    stores the other side. A translatable field has a second key after
    it, with its values in each language (ADR 0026): in a record, the
    field has the value of the selected language, and the second key the
    values of all languages. A file field has the name, the size, the
    type, and the URL of its file (`FileValue`), but the create input
    does not have it: the app uploads the file after the create (ADR 0027).
    A field with a sequence always has a value, and the inputs do not
    have it: the database gives the next number of the sequence.
    """
    result: list[Member] = []
    for name, field in entity.stored_fields.items():
        ts_type = enum_type(entity_name, name) if field.type == "enum" else _TS_TYPES[field.type]
        has_default = field.default is not None
        result.append(
            Member(
                name=name,
                key=camel(name),
                element_id=field.id,
                ts_type=ts_type,
                nullable=not field.required
                and not has_default
                and field.type != "boolean"
                and field.sequence is None,
                input_required=field.required and not has_default,
                default=field.default
                if has_default
                else (False if field.type == "boolean" else None),
                field=field,
            )
        )
        if field.translatable:
            result.append(
                Member(
                    name=f"{name}_translations",
                    key=translations_key(name),
                    element_id=field.id,
                    ts_type=TRANSLATIONS_TYPE,
                    nullable=True,
                    input_required=False,
                    default=None,
                    translations=field,
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


def history_members(entity_name: str, entity: Entity) -> list[Member]:
    """Return the keys of the change log of an entity (ADR 0040), in source order.

    They are the keys of the fields and the relations that the log keeps:
    the entries have the name in the definition, and the records the key.
    """
    by_name = {m.name: m for m in members(entity_name, entity) if m.translations is None}
    return [by_name[name] for name in entity.history_members]


def history_user_key(definition: AppDefinition) -> str | None:
    """Return the key that names a user in the change log: the display field, else the user name.

    A computed or a file display field is not a column, so the user name
    names the user then. Without `auth`, the entries have no user.
    """
    auth = definition.auth
    if auth is None:
        return None
    users = definition.entities[auth.user_entity]
    name = users.display_field
    if name is None or users.fields[name].computed is not None or users.fields[name].is_file:
        name = auth.username_field
    return camel(name)


def has_history(definition: AppDefinition) -> bool:
    """Return True if an entity keeps a change log (ADR 0040)."""
    return any(entity.history is not None for entity in definition.entities.values())


def operations_of(definition: AppDefinition, entity_name: str) -> list[tuple[str, Any]]:
    """Return the operations on an entity, in source order, as (name, operation) pairs."""
    return [(n, op) for n, op in definition.operations.items() if op.entity == entity_name]


def query_operations(definition: AppDefinition) -> list[tuple[str, Operation]]:
    """Return the queries (ADR 0045), in source order, as (name, operation) pairs."""
    return [(n, op) for n, op in definition.operations.items() if op.kind == "query"]


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
        case "point":
            # A latitude and a longitude in degrees (ADR 0046).
            code = (
                "z.object({ lat: z.number().min(-90).max(90), lng: z.number().min(-180).max(180) })"
            )
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
    if member.translations is not None:
        # A value of one language: null or an empty text removes it.
        value = member.translations.model_copy(update={"required": False})
        code = f"z.record(z.string(), {zod_type(value)}.nullable())"
    elif member.field is not None:
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
    "translations_key": translations_key,
    "history_members": history_members,
    "has_history": has_history,
    "has_points": has_points,
    "has_available": has_available,
    "history_user_key": history_user_key,
    "has_notices": has_notices,
    "notice_plans": notice_plans,
    "notice_texts": notice_texts,
    "notice_links": notice_links,
    "notice_summary": notice_summary,
    "notice_ids": notice_ids,
    "has_mentions": has_mentions,
    "mention_plans": mention_plans,
    "mention_link": mention_link,
    "has_notice_emails": has_notice_emails,
    "email_notifications": email_notifications,
    "mock_notify": mock_notify,
    "operations_of": operations_of,
    "query_operations": query_operations,
    "inverse_lists": inverse_lists,
    "line_items": line_items,
    "lines_operations": lines_operations,
    "param_type": param_type,
    "zod_schema": zod_schema,
    "param_schema": param_schema,
    "ts_features": ts_features,
}
"""The template globals that the shared entity templates use."""
