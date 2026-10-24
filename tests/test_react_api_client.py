import re
from pathlib import Path

from appgen.bindings import react
from appgen.bindings.react.api_client import api_entities, data_source
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen.extensions import check_extensions
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"


def definition_text(example: str, data: str | None) -> str:
    text = (ROOT / "examples" / example / "app.yaml").read_text()
    if data is None:
        return text
    return re.sub(r"(?m)^app:\n", f"app:\n  x-react-data: {data}\n", text, count=1)


def files(example: str, data: str | None) -> dict[str, str]:
    definition = load_definition_text(
        definition_text(example, data), str(ROOT / "examples" / example / "app.yaml")
    )
    return {f.path: f.content for f in generate(definition, react.BINDING).files}


def test_without_the_key_the_app_uses_mock_data() -> None:
    output = files("project-tracker", None)
    assert "src/shared/api/mock-store.ts" in output
    assert "src/shared/api/http.ts" not in output
    assert (
        "new MockStore<Project, ProjectInput>(" in output["src/entities/project/api/project-api.ts"]
    )


def test_with_the_key_the_app_uses_the_api_client() -> None:
    output = files("project-tracker", "api")
    assert "src/shared/api/mock-store.ts" not in output
    assert "src/entities/project/api/project-mock-data.ts" not in output
    assert "src/shared/api/http-store.ts" in output
    api = output["src/entities/project/api/project-api.ts"]
    assert 'new HttpStore<Project, ProjectInput>("Project", "/projects", {' in api
    assert '"due_date": "dueDate",' in api
    assert '"owner_id": "ownerId",' in api
    assert '"member_ids": "members",' in api
    assert 'numbers: ["budget"],' in api
    assert "VITE_API_URL" in output["src/vite-env.d.ts"]
    assert "ARG VITE_API_URL" in output["Dockerfile"]


def test_the_endpoints_are_the_endpoints_of_the_fastapi_app() -> None:
    definition = load_definition_text(definition_text("project-tracker", "api"), str(EXAMPLE))
    assert data_source(definition) == "api"
    endpoints = {
        (e.operation, e.method, e.path) for e in api_entities(definition)["Project"].endpoints
    }
    assert ("list_projects", "GET", "/projects") in endpoints
    assert ("read_project", "GET", "/projects/{id}") in endpoints
    assert ("update_project", "PATCH", "/projects/{id}") in endpoints


def test_a_custom_operation_calls_its_endpoint_and_has_no_extension_file() -> None:
    output = files("room-booking", "api")
    operation = output["src/features/cancel-booking/api/cancel-booking.gen.ts"]
    assert 'await bookingApi.call("POST", "/cancel-booking", id, {' in operation
    assert '"reason": params.reason,' in operation
    assert not [path for path in output if path.endswith("cancel-booking.ext.ts")]
    auth = output["src/shared/auth/index.ts"]
    assert 'apiRequest("POST", "/auth/sign-in", { username, password })' in auth
    assert "MOCK_PASSWORD" not in auth


def test_the_key_takes_only_mock_or_api() -> None:
    definition = load_definition_text(definition_text("project-tracker", "rest"), str(EXAMPLE))
    assert validate_definition(definition) == []
    codes = [d.code for d in check_extensions(definition, [react.BINDING])]
    assert codes == ["invalid-value"]
