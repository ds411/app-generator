"""The FastAPI binding writes a typed client for each third-party API (ADR 0019)."""

import json
from pathlib import Path
from typing import Any

import pytest

from appgen.bindings.fastapi.integrations import PySample, python_name
from appgen.dsl import load_definition, load_definition_text
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
operations:
  check_order:
    kind: custom
    entity: Order
    apis: [pets]
"""

PETS = """\
apis:
  pets:
    document: pets.json
    base_url_env: PETS_API_URL
    security: { scheme: token, env: PETS_API_TOKEN }
    operations: [getPet, addPet, deletePet]
"""

DOCUMENT: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1"},
    "servers": [{"url": "https://pets.example.com/v1"}],
    "paths": {
        "/pets/{id}": {
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {}}],
            "get": {
                "operationId": "getPet",
                "parameters": [
                    {"name": "result", "in": "query", "schema": {"type": "string"}},
                    {"name": "X-Trace", "in": "header", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "A pet.",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        },
                    }
                },
            },
            "delete": {"operationId": "deletePet", "responses": {"204": {"description": "No."}}},
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
                                "properties": {"name": {"type": "string"}},
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Added.",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        },
                    }
                },
            },
        },
    },
    "components": {
        "securitySchemes": {"token": {"type": "http", "scheme": "bearer"}},
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "birthDate": {"type": "string", "format": "date"},
                    "class": {"type": "string", "enum": ["dog", "cat"]},
                },
            }
        },
    },
}


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def tracker() -> dict[str, str]:
    return _files(generate(load_definition(EXAMPLE), find_binding("fastapi")))


@pytest.fixture
def pets(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "pets.json").write_text(json.dumps(DOCUMENT))
    definition = load_definition_text(BASE + PETS, str(tmp_path / "app.yaml"))
    return _files(generate(definition, find_binding("fastapi")))


def test_each_api_gets_a_package_with_its_models_and_its_client(tracker: dict[str, str]) -> None:
    for module in ("holidays", "exchange_rates"):
        for name in ("__init__.py", "models.py", "client.py"):
            assert f"app/integrations/{module}/{name}" in tracker
        assert f"tests/integrations/test_{module}.py" in tracker
        assert f"tests/integrations/{module}_examples.json" in tracker
    client = tracker["app/integrations/holidays/client.py"]
    assert "class HolidaysClient(ApiClient):" in client
    assert "    # @trace apis.holidays.operations.getPublicHolidays\n" in client
    assert "async def get_public_holidays(self, year: int, country_code: str)" in client
    assert "HolidaysClientDep = Annotated[HolidaysClient, Depends(get_holidays_client)]" in client
    models = tracker["app/integrations/holidays/models.py"]
    assert "class PublicHoliday(pydantic.BaseModel):" in models
    assert 'global_: bool = pydantic.Field(validation_alias="global"' in models
    examples = json.loads(tracker["tests/integrations/holidays_examples.json"])
    assert examples["getPublicHolidays"][0]["name"] == "New Year's Day"


def test_the_settings_and_the_deployment_files_read_the_base_url_and_the_secret(
    tracker: dict[str, str],
) -> None:
    assert 'holidays_api_url: str = "https://date.nager.at/api/v3"' in tracker["app/core/config.py"]
    assert 'exchange_rates_api_key: str = ""' in tracker["app/core/config.py"]
    assert "HOLIDAYS_API_URL=https://date.nager.at/api/v3\n" in tracker[".env.example"]
    assert "EXCHANGE_RATES_API_KEY=\n" in tracker[".env.example"]
    assert (
        "HOLIDAYS_API_URL: ${HOLIDAYS_API_URL:-https://date.nager.at/api/v3}"
        in tracker["compose.yaml"]
    )
    assert "EXCHANGE_RATES_API_KEY=\n" in tracker["deploy/kubernetes/secret.example.env"]
    assert "EXCHANGE_RATES_API_KEY" not in tracker["deploy/kubernetes/config.env"]
    assert '"httpx>=0.28",' in tracker["pyproject.toml"]


def test_a_custom_operation_gets_the_clients_of_its_apis(tracker: dict[str, str]) -> None:
    endpoint = tracker["app/features/tasks/schedule_task_gen.py"]
    assert "from app.integrations.holidays.client import HolidaysClientDep" in endpoint
    assert "    holidays: HolidaysClientDep,\n" in endpoint
    assert "schedule_task(session, record, params, holidays)" in endpoint
    stub = tracker["app/features/tasks/schedule_task_ext.py"]
    assert "from app.integrations.holidays.client import HolidaysClient" in stub
    assert "    holidays: HolidaysClient,\n" in stub
    conftest = tracker["tests/conftest.py"]
    assert "app.dependency_overrides[get_holidays_client] = mock_holidays_client" in conftest


def test_a_bearer_token_an_inline_body_and_an_answer_without_content(
    pets: dict[str, str],
) -> None:
    client = pets["app/integrations/pets/client.py"]
    assert '        token: str = "",\n' in client
    assert 'headers = {"Authorization": f"Bearer {token}"} if token else None' in client
    assert "async def delete_pet(self, id: pydantic.JsonValue) -> None:" in client
    assert "async def add_pet(self, body: AddPetBody) -> Pet:" in client
    # A parameter cannot have the name of a local variable of the tests.
    assert "result_: str | None = None" in client
    assert 'headers={"X-Trace": x_trace}' in client
    models = pets["app/integrations/pets/models.py"]
    assert 'type PetClass = typing.Literal["dog", "cat"]' in models
    assert "    id: uuid.UUID\n" in models
    assert "birth_date: dt.date | None = pydantic.Field(" in models
    assert "class_: PetClass | None = pydantic.Field(" in models
    tests = pets["tests/integrations/test_pets.py"]
    assert 'assert requests[0].headers["Authorization"] == "Bearer secret"' in tests
    assert 'pets_api_token: str = ""' in pets["app/core/config.py"]
    assert "client = PetsClient(settings.pets_api_url, settings.pets_api_token)" in client


def test_an_app_without_apis_has_no_clients() -> None:
    definition = load_definition_text(BASE.split("operations:")[0])
    files = _files(generate(definition, find_binding("fastapi")))
    assert not [p for p in files if "integrations" in p]
    dependencies = files["pyproject.toml"].split("[dependency-groups]")[0]
    assert "httpx" not in dependencies
    assert "mock_" not in files["tests/conftest.py"]


def test_python_names_avoid_keywords_reserved_names_and_duplicates() -> None:
    taken: set[str] = set()
    names = ["localName", "global", "model_config", "2fa", "self", "local_name", "-"]
    assert [python_name(n, taken) for n in names] == [
        "local_name",
        "global_",
        "model_config_",
        "n_2_fa",
        "self_",
        "local_name_2",
        "value",
    ]


def test_a_long_sample_gets_one_item_on_each_line_as_ruff_formats_it() -> None:
    short = PySample({"a": 1}, None)
    assert short.line("body") == 'body = {"a": 1}'
    items = {f"key{n}": "a long value of the sample" for n in range(4)}
    assert PySample(items, None).line("body", 0).splitlines() == [
        "body = {",
        '    "key0": "a long value of the sample",',
        '    "key1": "a long value of the sample",',
        '    "key2": "a long value of the sample",',
        '    "key3": "a long value of the sample",',
        "}",
    ]
    nested = PySample({"items": [items]}, "Order")
    assert nested.line("body", 4).splitlines() == [
        "body = pydantic.TypeAdapter(Order).validate_python(",
        "        {",
        '            "items": [',
        "                {",
        '                    "key0": "a long value of the sample",',
        '                    "key1": "a long value of the sample",',
        '                    "key2": "a long value of the sample",',
        '                    "key3": "a long value of the sample",',
        "                }",
        "            ]",
        "        }",
        "    )",
    ]
