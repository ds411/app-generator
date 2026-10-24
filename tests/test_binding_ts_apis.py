"""The TypeScript clients of the third-party APIs, and the Next.js client (ADR 0019)."""

import json
from pathlib import Path
from typing import Any

import pytest

from appgen.bindings.shared.integrations import ts_apis, ts_key, ts_type
from appgen.dsl import load_definition, load_definition_text
from appgen.dsl.openapi import (
    AnySchema,
    ArraySchema,
    MapSchema,
    ObjectSchema,
    Ref,
    ScalarSchema,
    UnionSchema,
)
from appgen.gen import GenerationResult, find_binding, generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

BASE = """\
version: 0
app: { name: shop, title: Shop }
entities:
  Order:
    crud: true
    fields:
      number: { type: string }
apis:
  client:
    document: pets.json
    base_url_env: PETS_API_URL
    security: { scheme: token, env: PETS_API_TOKEN }
    operations: [constructor, listPets, deletePet]
"""

PET = {"$ref": "#/components/schemas/Pet"}

DOCUMENT: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1"},
    "servers": [{"url": "https://pets.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    {"name": "X-Trace", "in": "header", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "Pets.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Pet"},
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "operationId": "constructor",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                    }
                },
                "responses": {"204": {"description": "Added."}},
            },
        },
        "/pets/{id}": {
            "delete": {
                "operationId": "deletePet",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"204": {"description": "Deleted."}},
            }
        },
    },
    "components": {
        "securitySchemes": {"token": {"type": "http", "scheme": "bearer"}},
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "The name."},
                    "birth-date": {"type": "string", "format": "date"},
                    "kind": {"$ref": "#/components/schemas/ListPetsParams"},
                },
            },
            "ListPetsParams": {"type": "string"},
        },
    },
}


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def tracker() -> dict[str, str]:
    return _files(generate(load_definition(EXAMPLE), find_binding("nextjs")))


def test_the_typescript_type_of_each_schema() -> None:
    enum = ScalarSchema("string", None, ("a", "b"))
    assert ts_type(Ref("Pet")) == "Pet"
    assert ts_type(enum) == '"a" | "b"'
    assert ts_type(ScalarSchema("integer", "int64", ())) == "number"
    assert ts_type(ScalarSchema("null", None, ())) == "null"
    assert ts_type(ArraySchema(enum)) == '("a" | "b")[]'
    assert ts_type(ArraySchema(Ref("Pet"))) == "Pet[]"
    assert ts_type(MapSchema(ScalarSchema("number", None, ()))) == "Record<string, number>"
    union = UnionSchema((ArraySchema(enum), ScalarSchema("null", None, ()), enum))
    assert ts_type(union) == '("a" | "b")[] | null | "a" | "b"'
    assert ts_type(AnySchema()) == "unknown"
    assert ts_type(ObjectSchema(())) == "unknown"


def test_a_json_name_that_is_not_an_identifier_gets_quotes() -> None:
    assert ts_key("name") == "name"
    assert ts_key("birth-date") == '"birth-date"'


def test_the_names_of_the_folder_the_methods_and_the_params_do_not_clash(
    tmp_path: Path,
) -> None:
    (tmp_path / "pets.json").write_text(json.dumps(DOCUMENT))
    api = ts_apis(load_definition_text(BASE, str(tmp_path / "app.yaml")))["client"]
    assert api.folder == "client-api"
    construct, list_pets, delete_pet = api.methods
    assert [m.name for m in api.methods] == ["constructor2", "listPets", "deletePet"]
    assert list_pets.params_type == "ListPetsParams2"
    assert list_pets.arguments() == "params: ListPetsParams2 = {}"
    assert list_pets.request_lines() == [
        "query: { limit: params.limit },",
        'headers: { "X-Trace": params["X-Trace"] },',
    ]
    assert construct.arguments() == "body?: Pet"
    assert delete_pet.returns == "void"
    assert delete_pet.request_lines() == ["path: { id: params.id },"]


def test_each_api_gets_a_server_only_client_with_its_types(tracker: dict[str, str]) -> None:
    for folder in ("holidays", "exchange-rates"):
        for name in ("index.ts", "types.ts", "client.ts"):
            assert f"src/shared/api/{folder}/{name}" in tracker
    http = tracker["src/shared/api/third-party.ts"]
    assert http.splitlines()[1] == "// @trace apis.holidays file"
    assert 'import "server-only";' in http
    assert "export class ApiError extends Error" in http
    client = tracker["src/shared/api/holidays/client.ts"]
    assert 'import "server-only";' in client
    assert "  // @trace apis.holidays.operations.getPublicHolidays\n" in client
    assert (
        "  async getPublicHolidays(params: GetPublicHolidaysParams): Promise<PublicHoliday[]> {"
        in client
    )
    assert "baseUrl: process.env.HOLIDAYS_API_URL || undefined," in client
    rates = tracker["src/shared/api/exchange-rates/client.ts"]
    assert 'headers: options.secret ? { "X-Api-Key": options.secret } : {},' in rates
    assert "secret: process.env.EXCHANGE_RATES_API_KEY," in rates
    types = tracker["src/shared/api/holidays/types.ts"]
    assert "export interface PublicHoliday {" in types
    assert "  counties?: string[] | null;" in types
    assert 'export type HolidayType = "Public" | "Bank"' in types


def test_the_environment_files_list_the_base_url_and_the_secret(tracker: dict[str, str]) -> None:
    assert "HOLIDAYS_API_URL=https://date.nager.at/api/v3\n" in tracker[".env.example"]
    assert "EXCHANGE_RATES_API_KEY=\n" in tracker[".env.example"]
    compose = tracker["compose.yaml"]
    assert "HOLIDAYS_API_URL: ${HOLIDAYS_API_URL:-https://date.nager.at/api/v3}" in compose
    assert "EXCHANGE_RATES_API_KEY: ${EXCHANGE_RATES_API_KEY:-}" in compose
    assert "## Third-party APIs" in tracker["README.md"]


def test_an_app_without_apis_has_no_clients() -> None:
    definition = load_definition_text(BASE.split("apis:")[0])
    files = _files(generate(definition, find_binding("nextjs")))
    assert "src/shared/api/third-party.ts" not in files
    assert "Third-party APIs" not in files["README.md"]
