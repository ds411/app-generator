"""Tests of the `apis` section: the OpenAPI reader, the loader, and the validator (ADR 0019)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from appgen.dsl import AppDefinition, DefinitionError, load_definition, load_definition_text
from appgen.dsl.apis import Api
from appgen.dsl.openapi import (
    AnySchema,
    ArraySchema,
    DocumentError,
    MapSchema,
    ObjectSchema,
    Ref,
    ScalarSchema,
    UnionSchema,
    read_document,
    sample,
    type_name,
)
from appgen.dsl.validator import validate_definition
from appgen.gen import find_binding, generate, read_manifest, write_result

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

BASE = """\
version: 0
app: { name: shop, title: Shop }
entities:
  Order:
    fields:
      number: { type: string }
"""

DOCUMENT: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1"},
    "servers": [
        {"url": "https://{region}.pets.example.com/v1/", "variables": {"region": {"default": "eu"}}}
    ],
    "paths": {
        "/pets/{id}": {
            "parameters": [{"name": "id", "in": "path", "schema": {"type": "string"}}],
            "get": {
                "operationId": "getPet",
                "parameters": [
                    {
                        "name": "fields",
                        "in": "query",
                        "schema": {"type": "array", "items": {"type": "string"}},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "A pet.",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        },
                    },
                    "404": {"description": "No pet."},
                },
            },
            "delete": {
                "operationId": "deletePet",
                "responses": {"204": {"description": "Deleted."}},
            },
        },
        "/pets": {
            "post": {
                "operationId": "addPet",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "tags": {"type": "object"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Added.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"},
                                "examples": {
                                    "rex": {"value": {"id": "p1", "name": "Rex", "kind": "dog"}}
                                },
                            }
                        },
                    }
                },
            },
            "get": {
                "operationId": "listPets",
                "parameters": [
                    {"name": "session", "in": "cookie", "schema": {"type": "object"}},
                    {"name": "filter", "in": "querystring", "schema": {"type": "string"}},
                ],
                "requestBody": {"content": {"application/xml": {}}},
                "responses": {"200": {"description": "Pets.", "content": {"text/csv": {}}}},
            },
        },
    },
    "components": {
        "securitySchemes": {
            "key": {"type": "apiKey", "in": "header", "name": "X-Key"},
            "token": {"type": "http", "scheme": "Bearer"},
            "basic": {"type": "http", "scheme": "basic"},
            "cookie": {"type": "apiKey", "in": "cookie", "name": "sid"},
        },
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string", "description": "The name."},
                    "kind": {"$ref": "#/components/schemas/Kind"},
                    "owner": {
                        "type": "object",
                        "nullable": True,
                        "properties": {"email": {"type": "string", "format": "email"}},
                    },
                    "parent": {"$ref": "#/components/schemas/Pet"},
                    "weight": {"type": ["number", "null"]},
                    "extra": {"additionalProperties": {"type": "integer"}},
                    "any": {},
                    "choice": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                },
            },
            "Kind": {"type": "string", "enum": ["dog", "cat"]},
            "Unused": {"type": "object", "properties": {"x": {"type": "string"}}},
        },
    },
}


def write_document(folder: Path, data: object, name: str = "pets.json") -> Path:
    path = folder / name
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return path


def definition(folder: Path, apis: str, document: object = DOCUMENT) -> AppDefinition:
    write_document(folder, document)
    return load_definition_text(BASE + apis, str(folder / "app.yaml"))


def codes(found: AppDefinition) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in validate_definition(found)]


PETS = """\
apis:
  pets:
    document: pets.json
    base_url_env: PETS_API_URL
    operations: [getPet, addPet]
"""


def test_the_reader_gives_the_title_the_server_and_the_operation_ids(tmp_path: Path) -> None:
    document = read_document(write_document(tmp_path, DOCUMENT))

    assert document.title == "Pets"
    assert document.version == "3.1.0"
    assert document.base_url == "https://eu.pets.example.com/v1"
    assert document.operation_ids == ("getPet", "deletePet", "addPet", "listPets")

    assert document.hash.startswith("sha256:")
    assert document.security_schemes["token"].scheme == "bearer"
    supported = [n for n, s in document.security_schemes.items() if s.supported]
    assert supported == ["key", "token", "basic"]


def test_the_selection_keeps_only_the_schemas_that_the_operations_need(tmp_path: Path) -> None:
    spec = read_document(write_document(tmp_path, DOCUMENT)).select(["getPet", "addPet"])

    assert [o.id for o in spec.operations] == ["getPet", "addPet"]
    assert [s.name for s in spec.schemas] == ["AddPetBody", "Kind", "Pet", "PetOwner"]
    get_pet, add_pet = spec.operations
    assert [(p.name, p.location, p.required) for p in get_pet.parameters] == [
        ("id", "path", True),
        ("fields", "query", False),
    ]
    assert get_pet.parameters[1].schema == ArraySchema(ScalarSchema("string"))
    assert get_pet.result == Ref("Pet")
    assert add_pet.body == Ref("AddPetBody")
    assert add_pet.body_required
    assert add_pet.status == "201"
    assert add_pet.example == {"id": "p1", "name": "Rex", "kind": "dog"}


def test_an_example_of_a_json_answer_can_be_json_text(tmp_path: Path) -> None:
    # The document of Jira Cloud gives each example as a string with the JSON text.
    document = copy.deepcopy(DOCUMENT)
    added = document["paths"]["/pets"]["post"]["responses"]["201"]["content"]
    added["application/json"].pop("examples")
    added["application/json"]["example"] = '{"id": "p2", "name": "Tom"}'

    spec = read_document(write_document(tmp_path, document)).select(["addPet"])
    assert spec.operations[0].example == {"id": "p2", "name": "Tom"}

    # A string that is not JSON text gives the sample of the schema.
    added["application/json"]["example"] = "Tom"
    spec = read_document(write_document(tmp_path, document)).select(["addPet"])
    assert spec.operations[0].example == {"id": "string", "name": "string"}


def test_a_string_example_of_a_string_answer_stays_a_string(tmp_path: Path) -> None:
    document = copy.deepcopy(DOCUMENT)
    content = document["paths"]["/pets"]["post"]["responses"]["201"]["content"]
    content["application/json"] = {"schema": {"type": "string"}, "example": '{"id": "p2"}'}

    spec = read_document(write_document(tmp_path, document)).select(["addPet"])

    assert spec.operations[0].example == '{"id": "p2"}'


def test_the_normal_form_names_each_object_schema(tmp_path: Path) -> None:
    spec = read_document(write_document(tmp_path, DOCUMENT)).select(["getPet"])

    pet = spec.schema("Pet").schema
    assert isinstance(pet, ObjectSchema)
    by_name = {p.name: p for p in pet.properties}
    assert by_name["name"].required
    assert by_name["name"].description == "The name."
    assert not by_name["kind"].required
    assert by_name["kind"].schema == Ref("Kind")
    assert by_name["owner"].schema == UnionSchema((Ref("PetOwner"), ScalarSchema("null")))
    assert by_name["parent"].schema == Ref("Pet")
    assert by_name["weight"].schema == UnionSchema((ScalarSchema("number"), ScalarSchema("null")))
    assert by_name["extra"].schema == MapSchema(ScalarSchema("integer"))
    assert by_name["any"].schema == AnySchema()
    assert by_name["choice"].schema == UnionSchema(
        (ScalarSchema("string"), ScalarSchema("integer"))
    )
    assert spec.schema("Kind").schema == ScalarSchema("string", None, ("dog", "cat"))


def test_a_sample_fills_the_required_properties(tmp_path: Path) -> None:
    spec = read_document(write_document(tmp_path, DOCUMENT)).select(["getPet"])

    assert spec.operations[0].example == {"id": "string", "name": "string"}
    assert sample(Ref("PetOwner"), spec) == {}
    assert sample(ScalarSchema("string", "date"), spec) == "2026-01-01"


def test_all_of_merges_the_properties_of_its_parts() -> None:
    document = read_document(EXAMPLE.parent / "apis" / "exchange-rates.openapi.json")
    spec = document.select(["convertAmount"])

    conversion = spec.schema("Conversion").schema
    assert isinstance(conversion, ObjectSchema)
    assert [(p.name, p.required) for p in conversion.properties] == [
        ("from", True),
        ("to", True),
        ("amount", True),
        ("rate", True),
        ("result", True),
    ]


def test_the_reader_reads_yaml_and_turns_dates_into_text() -> None:
    document = read_document(EXAMPLE.parent / "apis" / "public-holidays.openapi.yaml")
    spec = document.select(["getPublicHolidays"])

    example = spec.operations[0].example
    assert isinstance(example, list)
    assert example[0] == {
        "date": "2026-01-01",
        "localName": "Neujahr",
        "name": "New Year's Day",
        "countryCode": "DE",
        "global": True,
        "counties": None,
        "types": ["Public"],
    }


def test_the_selection_reports_what_a_client_cannot_send_or_read(tmp_path: Path) -> None:
    spec = read_document(write_document(tmp_path, DOCUMENT)).select(["listPets"])

    assert [problem for _, problem in spec.problems] == [
        "The cookie parameter 'session' is not a text, a number, or a boolean. The clients "
        "send only such cookie parameters.",
        "The parameter 'filter' is in a querystring. The clients send only path, query, "
        "header, and cookie parameters.",
        "The request body is not JSON, a form, or a multipart form. The clients send only "
        "these bodies.",
    ]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("[1, 2]", "An OpenAPI document is a mapping."),
        ('{"swagger": "2.0"}', "Swagger 2.0 is not supported."),
        ('{"openapi": "3.2.0"}', "The OpenAPI version '3.2.0' is not supported."),
        ('{"openapi": "3.0.3"}', "The key 'info' is missing."),
        (
            '{"openapi": "3.0.3", "info": {"title": "x", "version": "1"},'
            ' "paths": {"/a": {"get": {"operationId": "a"}}}}',
            "The key 'responses' is missing.",
        ),
        (
            '{"openapi": "3.0.3", "info": {"title": "x", "version": "1"},'
            ' "paths": {"/a": {"$ref": "other.yaml#/paths/a"}}}',
            "The $ref 'other.yaml#/paths/a' is not local.",
        ),
        (
            '{"openapi": "3.0.3", "info": {"title": "x", "version": "1"},'
            ' "paths": {"/a": {"$ref": "#/nothing"}}}',
            "The $ref '#/nothing' does not resolve.",
        ),
        (
            "openapi: 3.0.3\ninfo: { title: x, version: '1' }\npaths:\n"
            "  /a: { get: { operationId: a, responses: {} } }\n"
            "  /b: { get: { operationId: a, responses: {} } }\n",
            "The operation ID 'a' is not unique.",
        ),
        ("openapi: [", "the document is not YAML or JSON"),
    ],
)
def test_the_reader_rejects_a_document_that_is_not_valid(
    tmp_path: Path, document: str, message: str
) -> None:
    path = write_document(tmp_path, document, "doc.yaml")

    with pytest.raises(DocumentError) as error:
        read_document(path)

    assert message in str(error.value)


def test_the_error_gives_the_line_in_a_yaml_document(tmp_path: Path) -> None:
    path = write_document(
        tmp_path, "openapi: 3.0.3\ninfo:\n  version: '1'\npaths: {}\n", "doc.yaml"
    )

    with pytest.raises(DocumentError, match=r"doc\.yaml:3:3 \(/info\)"):
        read_document(path)


def test_each_api_and_each_operation_is_an_element(tmp_path: Path) -> None:
    found = definition(tmp_path, PETS)

    assert codes(found) == []
    assert isinstance(found.find("apis.pets"), Api)
    assert found.find("apis.pets.operations.getPet") is not None
    assert found.find("apis.pets.operations.addPet") is not None
    api = found.apis["pets"]
    assert api.label == "Pets"
    assert [o.id for o in api.spec.operations] == ["getPet", "addPet"]


def test_the_mapping_form_of_the_operations_has_descriptions(tmp_path: Path) -> None:
    found = definition(
        tmp_path,
        PETS.replace(
            "operations: [getPet, addPet]",
            "title: Pet store\n    operations:\n      getPet: { description: Show a pet. }",
        ),
    )

    assert codes(found) == []
    assert found.apis["pets"].operations["getPet"].description == "Show a pet."
    assert found.apis["pets"].label == "Pet store"


def test_the_location_of_an_operation_in_the_list_is_its_item(tmp_path: Path) -> None:
    found = definition(tmp_path, PETS.replace("[getPet, addPet]", "[getPet, getPets]"))

    [diagnostic] = validate_definition(found)
    assert diagnostic.code == "unknown-reference"
    assert diagnostic.element_id == "apis.pets.operations.getPets"
    assert diagnostic.hint == "Did you mean 'getPet'?"
    assert (diagnostic.location.line, diagnostic.location.column) == (11, 26)


def test_an_operation_twice_in_the_list_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DefinitionError) as error:
        definition(tmp_path, PETS.replace("[getPet, addPet]", "[getPet, getPet]"))

    assert [d.code for d in error.value.diagnostics] == ["duplicate-name"]


def test_an_operation_id_must_be_a_trace_segment(tmp_path: Path) -> None:
    with pytest.raises(DefinitionError) as error:
        definition(tmp_path, PETS.replace("[getPet, addPet]", "[get-pet]"))

    assert [d.code for d in error.value.diagnostics] == ["invalid-name"]


def test_a_document_that_does_not_exist_is_an_error(tmp_path: Path) -> None:
    found = definition(tmp_path, PETS.replace("pets.json", "missing.json"))

    [diagnostic] = validate_definition(found)
    assert diagnostic.code == "invalid-document"
    assert diagnostic.message.startswith("The OpenAPI document 'missing.json' is not valid:")
    assert "Cannot read the document" in diagnostic.message


def test_a_document_must_be_a_local_file(tmp_path: Path) -> None:
    found = definition(tmp_path, PETS.replace("pets.json", "https://example.com/pets.json"))

    assert codes(found) == [("invalid-document", "apis.pets")]


@pytest.mark.parametrize(
    ("security", "expected"),
    [
        ("{ scheme: key, env: PETS_API_KEY }", []),
        ("{ scheme: token, env: PETS_TOKEN }", []),
        ("{ scheme: keys, env: PETS_API_KEY }", [("unknown-reference", "apis.pets")]),
        ("{ scheme: basic, username_env: PETS_USER, env: PETS_PASSWORD }", []),
        ("{ scheme: basic, env: PETS_PASSWORD }", [("missing-key", "apis.pets")]),
        ("{ scheme: basic, username_env: PETS_USER }", [("missing-key", "apis.pets")]),
        (
            "{ scheme: basic, username_env: PETS_USER, env: PETS_PASSWORD, scopes: [a] }",
            [("invalid-option", "apis.pets")],
        ),
        (
            "{ scheme: key, username_env: PETS_USER, env: PETS_KEY }",
            [("invalid-option", "apis.pets")],
        ),
        (
            "{ scheme: basic, username_env: DATABASE_URL, env: PETS_PASSWORD }",
            [("reserved-name", "apis.pets")],
        ),
        (
            "{ scheme: basic, username_env: NEXT_PUBLIC_PETS_USER, env: PETS_PASSWORD }",
            [("reserved-name", "apis.pets")],
        ),
        (
            "{ scheme: basic, username_env: PETS_PASSWORD, env: PETS_PASSWORD }",
            [("duplicate-name", "apis.pets")],
        ),
        ("{ scheme: cookie, env: PETS_SESSION }", [("unsuitable-security", "apis.pets")]),
        ("{ scheme: key, env: PETS_API_URL }", [("duplicate-name", "apis.pets")]),
        ("{ scheme: key, env: DATABASE_URL }", [("reserved-name", "apis.pets")]),
        ("{ scheme: key, env: PASSWORD_RESET_URL }", [("reserved-name", "apis.pets")]),
        ("{ scheme: key, env: NEXT_PUBLIC_PETS_KEY }", [("reserved-name", "apis.pets")]),
        ("{ scheme: key, env: VITE_PETS_KEY }", [("reserved-name", "apis.pets")]),
    ],
)
def test_the_security_scheme_exists_and_suits_the_clients(
    tmp_path: Path, security: str, expected: list[tuple[str, str]]
) -> None:
    found = definition(tmp_path, PETS + f"    security: {security}\n")

    assert codes(found) == expected


def test_an_operation_that_a_client_cannot_call_is_an_error(tmp_path: Path) -> None:
    found = definition(tmp_path, PETS.replace("[getPet, addPet]", "[listPets]"))

    assert codes(found) == [("unsuitable-operation", "apis.pets.operations.listPets")] * 3


def test_an_exposed_operation_takes_each_parameter_as_a_query_parameter(tmp_path: Path) -> None:
    exposed = PETS + "    expose: true\n"
    assert codes(definition(tmp_path, exposed)) == []

    document = copy.deepcopy(DOCUMENT)
    nested = {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}
    document["paths"]["/pets/{id}"]["get"]["parameters"] += [
        {"name": "filter", "in": "query", "schema": {"$ref": "#/components/schemas/Pet"}},
        {"name": "grid", "in": "query", "schema": nested},
        {"name": "id", "in": "header", "schema": {"type": "string"}},
    ]
    found = definition(tmp_path, exposed, document)

    diagnostics = validate_definition(found)
    assert [(d.code, d.element_id) for d in diagnostics] == [
        ("unsuitable-operation", "apis.pets.operations.getPet"),
        ("unsuitable-operation", "apis.pets.operations.getPet"),
        ("unsuitable-operation", "apis.pets.operations.getPet"),
    ]
    assert [d.message.split(": ", 1)[1] for d in diagnostics] == [
        "a query parameter cannot hold the parameter 'filter'. "
        "Its endpoint takes each parameter as a query parameter.",
        "a query parameter cannot hold the parameter 'grid'. "
        "Its endpoint takes each parameter as a query parameter.",
        "two parameters have the name 'id'. "
        "Its endpoint takes each parameter as a query parameter.",
    ]
    # Without `expose`, the client sends these parameters.
    assert codes(definition(tmp_path, PETS, document)) == []


def test_a_custom_operation_names_the_apis_that_it_calls(tmp_path: Path) -> None:
    operations = """\
operations:
  check_order: { kind: custom, entity: Order, apis: [pets] }
  ship_order: { kind: custom, entity: Order, apis: [pet, pets, pets] }
  list_orders: { kind: list, entity: Order, apis: [pets] }
"""
    found = definition(tmp_path, PETS + operations)

    assert codes(found) == [
        ("duplicate-name", "operations.ship_order"),
        ("unknown-reference", "operations.ship_order"),
        ("invalid-option", "operations.list_orders"),
    ]


def test_the_manifest_records_the_hash_of_each_document(tmp_path: Path) -> None:
    found = load_definition(EXAMPLE)
    out = tmp_path / "out"

    write_result(generate(found, find_binding("minimal")), out, "minimal")

    manifest = read_manifest(out)
    assert manifest is not None
    hashes = {name: api.openapi.hash for name, api in found.apis.items() if api.openapi}
    commits = found.webhooks["commits"].openapi
    assert commits is not None
    assert manifest.documents == {
        "apis/documents.openapi.yaml": hashes["documents"],
        "apis/exchange-rates.openapi.json": hashes["exchange_rates"],
        "apis/finance.openapi.yaml": hashes["finance"],
        "apis/public-holidays.openapi.yaml": hashes["holidays"],
        "webhooks/commits.openapi.yaml": commits.hash,
    }


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("public_holiday", "PublicHoliday"),
        ("getHolidays", "GetHolidays"),
        ("holiday.v3", "HolidayV3"),
        ("3d-model", "Schema3dModel"),
    ],
)
def test_type_names_are_pascal_case(text: str, name: str) -> None:
    assert type_name(text) == name
