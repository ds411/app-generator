"""Tests of the TypeScript helpers that the Next.js and the React bindings share."""

import pytest

from appgen.bindings.shared.typescript import members, param_schema, zod_schema, zod_type
from appgen.dsl.model import Entity, Field


def _field(**values: object) -> Field:
    return Field.model_validate(values)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"type": "string"}, "z.string()"),
        ({"type": "string", "required": True}, "z.string().min(1)"),
        ({"type": "text", "min_length": 0, "max_length": 9}, "z.string().max(9)"),
        ({"type": "email", "max_length": 254}, "z.email().max(254)"),
        ({"type": "string", "pattern": "^a$"}, 'z.string().regex(new RegExp("^a$"))'),
        ({"type": "integer", "min": 0, "max": 10}, "z.int32().min(0).max(10)"),
        ({"type": "decimal", "min": 0.5}, "z.number().min(0.5)"),
        ({"type": "date"}, "z.iso.date()"),
        ({"type": "datetime"}, "z.iso.datetime({ offset: true })"),
        ({"type": "enum", "values": ["a", "b"]}, 'z.enum(["a", "b"])'),
        ({"type": "json"}, "z.json()"),
    ],
)
def test_zod_type_has_the_rules_of_the_field(values: dict[str, object], expected: str) -> None:
    assert zod_type(_field(**values)) == expected


def test_zod_schema_follows_the_create_input() -> None:
    entity = Entity.model_validate(
        {
            "fields": {
                "title": {"type": "string", "required": True},
                "status": {
                    "type": "enum",
                    "values": ["todo", "done"],
                    "default": "todo",
                },
                "notes": {"type": "text"},
            },
            "relations": {
                "project": {
                    "kind": "many_to_one",
                    "target": "Project",
                    "required": True,
                },
                "tags": {
                    "kind": "many_to_many",
                    "target": "Tag",
                },
            },
        }
    )
    schemas = {m.key: zod_schema("Task", m) for m in members("Task", entity)}
    assert schemas == {
        "title": "z.string().min(1)",
        "status": "z.enum(taskStatusValues).optional()",
        "notes": "z.string().nullable().optional()",
        "projectId": "z.uuid()",
        "tags": "z.array(z.uuid()).optional()",
    }


def test_an_optional_param_accepts_null() -> None:
    assert param_schema(_field(type="boolean")) == "z.boolean().nullish()"
    assert param_schema(_field(type="uuid", required=True)) == "z.uuid()"
