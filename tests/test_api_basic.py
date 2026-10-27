"""APIs with HTTP Basic, for example Jira Cloud with an email address and an API token (#486)."""

import ast
import base64
import json
import re
from pathlib import Path
from typing import Any

import pytest

from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.gen import GenerationResult, find_binding, generate, write_result
from appgen.trace import check_traces

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "jira.yaml"
TEXT = FIXTURE.read_text()
OPERATIONS = ["getIssue", "searchAndReconsileIssuesUsingJql", "createIssue", "addComment"]


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


def _exposed() -> str:
    """Return the fixture with `expose: true` and the React data of the FastAPI app."""
    text = TEXT.replace("  name: support-desk\n", "  name: support-desk\n  x-react-data: api\n")
    url = "    base_url_env: JIRA_API_URL\n"
    return text.replace(url, url + "    expose: true\n")


@pytest.fixture(scope="module")
def fastapi() -> dict[str, str]:
    return _files(generate(load_definition(FIXTURE), find_binding("fastapi")))


@pytest.fixture(scope="module")
def nextjs() -> dict[str, str]:
    return _files(generate(load_definition(FIXTURE), find_binding("nextjs")))


def test_the_fixture_is_valid_and_has_the_basic_scheme_of_jira() -> None:
    definition = load_definition(FIXTURE)

    assert validate_definition(definition) == []
    api = definition.apis["jira"]
    assert api.security is not None
    assert api.security.variables == [("username_env", "JIRA_EMAIL"), ("env", "JIRA_API_TOKEN")]
    document = api.openapi
    assert document is not None
    assert document.base_url == "https://your-domain.atlassian.net"
    scheme = document.security_schemes["basicAuth"]
    assert (scheme.type, scheme.scheme, scheme.supported) == ("http", "basic", True)
    assert [o.id for o in api.spec.operations] == OPERATIONS
    # The document gives the examples as JSON text, and the reader reads them as JSON.
    assert all(isinstance(o.example, dict) for o in api.spec.operations)


@pytest.mark.parametrize("binding", ["fastapi", "nextjs", "react"])
def test_the_fixture_generates_with_each_binding_and_valid_traces(
    binding: str, tmp_path: Path
) -> None:
    definition = load_definition(FIXTURE)
    write_result(generate(definition, find_binding(binding)), tmp_path, binding)

    report = check_traces(definition, tmp_path)

    assert report.invalid == []


def test_the_fastapi_client_sends_http_basic(fastapi: dict[str, str]) -> None:
    client = fastapi["app/integrations/jira/client.py"]
    http = fastapi["app/integrations/http.py"]
    ast.parse(client)
    ast.parse(http)

    assert '        username: str = "",\n        password: str = "",\n' in client
    assert (
        '        headers = {"Authorization": basic_authorization(username, password)} '
        "if password else None\n"
    ) in client
    assert "settings.jira_api_url, settings.jira_email, settings.jira_api_token" in client
    assert "def basic_authorization(username: str, password: str) -> str:" in http
    assert 'credentials = f"{username}:{password}".encode()' in http
    config = fastapi["app/core/config.py"]
    assert '    jira_email: str = ""\n' in config
    assert '    jira_api_token: str = ""\n' in config


def test_the_fastapi_tests_check_the_header_with_a_user_name_that_is_not_ascii(
    fastapi: dict[str, str],
) -> None:
    test = fastapi["tests/integrations/test_jira.py"]
    expected = "Basic " + base64.b64encode("zoë@example.com:secret".encode()).decode()

    assert f'== "{expected}"' in test
    assert 'JiraClient("https://jira.test", "zoë@example.com", "secret", transport=transport)' in (
        test
    )
    assert "async def test_a_client_without_the_password_sends_no_credential() -> None:" in test


def test_the_fastapi_files_list_the_user_name_and_the_token_as_secrets(
    fastapi: dict[str, str],
) -> None:
    secrets = fastapi["deploy/kubernetes/secret.example.env"]
    assert "JIRA_EMAIL=\nJIRA_API_TOKEN=\n" in secrets
    assert "JIRA_EMAIL" not in fastapi["deploy/kubernetes/config.env"]
    assert "JIRA_EMAIL=\nJIRA_API_TOKEN=\n" in fastapi[".env.example"]
    assert (
        "      JIRA_EMAIL: ${JIRA_EMAIL:-}\n      JIRA_API_TOKEN: ${JIRA_API_TOKEN:-}\n"
        in (fastapi["compose.yaml"])
    )
    row = "| `jira` | `app/integrations/jira/client.py` | `JIRA_API_URL` | "
    assert row + "`JIRA_EMAIL` (user name), `JIRA_API_TOKEN` |" in fastapi["README.md"]
    # The texts of the document can have characters that look like others.
    assert '"app/integrations/*/*.py" = ["RUF001", "RUF002", "RUF003"]' in fastapi["pyproject.toml"]


def test_the_knative_service_reads_the_user_name_and_the_token_from_secrets() -> None:
    name = "  name: support-desk\n"
    text = TEXT.replace(name, name + "  x-fastapi-deploy: knative\n")
    definition = load_definition_text(text, str(FIXTURE))
    files = _files(generate(definition, find_binding("fastapi")))

    service = files["deploy/knative/service.yaml"]
    for env in ("JIRA_EMAIL", "JIRA_API_TOKEN"):
        assert f"            - name: {env}\n              valueFrom:\n" in service
        assert f"name: support-desk-{env.lower().replace('_', '-')}\n" in service
    readme = files["README.md"]
    for env in ("JIRA_EMAIL", "JIRA_API_TOKEN"):
        name = f"support-desk-{env.lower().replace('_', '-')}"
        assert f"kubectl create secret generic {name} --from-literal=latest='<{env}>'" in readme


def test_a_long_mapping_of_parameters_is_on_many_lines(fastapi: dict[str, str]) -> None:
    client = fastapi["app/integrations/jira/client.py"]

    assert '            query={\n                "jql": jql,\n' in client
    calls = [line for line in client.splitlines() if "query=" in line]
    assert calls
    assert max(len(line) for line in calls) <= 100
    test = fastapi["tests/integrations/test_jira.py"]
    assert (
        "async def test_search_and_reconsile_issues_using_jql_sends_the_request_and_reads_the_"
        "answer() -> (\n    None\n):\n"
    ) in test


def test_the_nextjs_client_sends_http_basic_with_utf8(nextjs: dict[str, str]) -> None:
    client = nextjs["src/shared/api/jira/client.ts"]
    http = nextjs["src/shared/api/third-party.ts"]

    assert "import { basicAuthorization, HttpClient, type ClientOptions } from" in client
    assert (
        'headers: options.secret ? { Authorization: basicAuthorization(options.username ?? "", '
        "options.secret) } : {},"
    ) in client
    assert "    username: process.env.JIRA_EMAIL,\n    secret: process.env.JIRA_API_TOKEN,\n" in (
        client
    )
    assert "  username?: string;\n" in http
    assert 'Buffer.from(`${username}:${password}`, "utf8").toString("base64")' in http
    # The token request of OAuth 2.0 is not in an app without OAuth 2.0.
    assert "btoa" not in http


def test_the_nextjs_files_list_the_user_name_and_the_token_as_secrets(
    nextjs: dict[str, str],
) -> None:
    assert "JIRA_EMAIL=\nJIRA_API_TOKEN=\n" in nextjs["deploy/kubernetes/secret.example.env"]
    assert "JIRA_EMAIL=\nJIRA_API_TOKEN=\n" in nextjs[".env.example"]
    assert "      JIRA_EMAIL: ${JIRA_EMAIL:-}\n" in nextjs["compose.yaml"]
    assert "`JIRA_EMAIL` (user name), `JIRA_API_TOKEN` |" in nextjs["README.md"]


def test_the_react_app_has_no_client_for_the_api_and_warns() -> None:
    result = generate(load_definition(FIXTURE), find_binding("react"))
    files = _files(result)

    # Only the extension file of the gaps of the operations.
    assert [path for path in files if "/jira/" in path] == ["src/shared/api/jira/client.ext.ts"]
    [warning] = result.warnings
    assert warning.startswith("The API 'jira' has a secret (JIRA_API_TOKEN)")
    gap = files["src/shared/api/jira/client.ext.ts"]
    for name in OPERATIONS:
        assert f"// @trace:gap apis.jira.operations.{name} file" in gap


def test_the_react_app_calls_the_exposed_api_through_the_fastapi_app() -> None:
    definition = load_definition_text(_exposed(), str(FIXTURE))
    assert validate_definition(definition) == []

    react = generate(definition, find_binding("react"))
    fastapi = _files(generate(definition, find_binding("fastapi")))

    assert react.warnings == []
    client = _files(react)["src/shared/api/jira/client.ts"]
    assert 'import { API_URL, apiFetch } from "@/shared/api/http";' in client
    assert "basicAuthorization" not in client
    assert "JIRA_API_TOKEN" not in client
    router = fastapi["app/integrations/jira/router.py"]
    endpoints = re.findall(r'@router\.\w+\(\s*"(/[a-z-]+)"', router)
    assert endpoints == [
        "/get-issue",
        "/search-and-reconsile-issues-using-jql",
        "/create-issue",
        "/add-comment",
    ]


def test_the_trimmed_document_keeps_the_original_server_and_schemes() -> None:
    path = ROOT / "tests" / "fixtures" / "jira" / "jira.openapi.json"
    document: dict[str, Any] = json.loads(path.read_text())

    assert document["servers"] == [{"url": "https://your-domain.atlassian.net"}]
    assert document["components"]["securitySchemes"]["basicAuth"] == {
        "description": "You can access this resource via basic auth.",
        "scheme": "basic",
        "type": "http",
    }
    paths: dict[str, dict[str, Any]] = document["paths"]
    operations: list[str] = [
        op["operationId"] for item in paths.values() for op in item.values() if "operationId" in op
    ]
    assert sorted(operations) == sorted(OPERATIONS)
