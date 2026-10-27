"""APIs with HTTP Basic and the credentials of each user, for example Jira (#487, ADR 0033)."""

import ast
import re
from pathlib import Path

import pytest

from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.diagnostics import DefinitionError, Diagnostic
from appgen.gen import GenerationResult, find_binding, generate, write_result
from appgen.trace import check_traces

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "jira-accounts.yaml"
TEXT = FIXTURE.read_text()
SECURITY = "    security: { scheme: basicAuth, per_user: true, check: getCurrentUser }\n"
CALENDAR = ROOT / "tests" / "fixtures" / "api-connections"


def _load(text: str) -> list[Diagnostic]:
    """Return the diagnostics of a variant of the fixture."""
    try:
        definition = load_definition_text(text, str(FIXTURE))
    except DefinitionError as error:
        return error.diagnostics
    return validate_definition(definition)


def _codes(text: str) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in _load(text)]


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


def _security(value: str) -> str:
    return TEXT.replace(SECURITY, f"    security: {value}\n")


def _mixed() -> str:
    """Return the fixture with a second API with the authorization code flow (ADR 0033)."""
    document = (CALENDAR / "calendar.openapi.yaml").as_posix()
    calendar = (
        "  calendar:\n"
        f"    document: {document}\n"
        "    base_url_env: CALENDAR_API_URL\n"
        "    security:\n"
        "      scheme: oauth\n"
        "      client_id_env: CALENDAR_CLIENT_ID\n"
        "      client_secret_env: CALENDAR_CLIENT_SECRET\n"
        "      flow: authorizationCode\n"
        "      scopes: [events:read]\n"
        "    operations: [listEvents]\n"
    )
    return TEXT.replace("\njobs:\n", f"{calendar}\njobs:\n")


@pytest.fixture(scope="module")
def fastapi() -> dict[str, str]:
    return _files(generate(load_definition(FIXTURE), find_binding("fastapi")))


@pytest.fixture(scope="module")
def nextjs() -> dict[str, str]:
    return _files(generate(load_definition(FIXTURE), find_binding("nextjs")))


def test_the_fixture_is_valid_and_has_the_credentials_of_each_user() -> None:
    definition = load_definition(FIXTURE)

    assert validate_definition(definition) == []
    api = definition.apis["jira"]
    assert api.security is not None
    assert api.security.variables == []
    assert (api.user_basic, api.per_user, api.user_flow) == (True, True, False)
    operation = api.check_operation
    assert operation is not None
    assert (operation.id, operation.method, operation.path) == (
        "getCurrentUser",
        "get",
        "/rest/api/3/myself",
    )


def test_the_check_is_optional() -> None:
    definition = load_definition_text(
        _security("{ scheme: basicAuth, per_user: true }"), str(FIXTURE)
    )

    assert validate_definition(definition) == []
    assert definition.apis["jira"].check_operation is None


@pytest.mark.parametrize("key", ["env: JIRA_API_TOKEN", "username_env: JIRA_EMAIL"])
def test_the_credentials_of_each_user_need_no_variables(key: str) -> None:
    found = _load(_security(f"{{ scheme: basicAuth, per_user: true, {key} }}"))

    assert [(d.code, d.element_id) for d in found] == [("invalid-option", "apis.jira")]
    name = key.partition(":")[0]
    assert found[0].message == (
        f"The key '{name}' does not suit the scheme 'basicAuth' (HTTP Basic with the "
        "credentials of each user)."
    )
    assert (
        found[0].hint
        == "Each user gives the user name and the password on the page '/connections'."
    )


def test_the_check_needs_per_user() -> None:
    variables = "username_env: JIRA_EMAIL, env: JIRA_API_TOKEN"
    text = _security(f"{{ scheme: basicAuth, {variables}, check: getCurrentUser }}")
    found = _load(text)

    assert [(d.code, d.element_id) for d in found] == [("invalid-option", "apis.jira")]
    assert found[0].message == "The key 'check' does not suit the scheme 'basicAuth' (HTTP Basic)."


def test_per_user_does_not_suit_oauth() -> None:
    found = _load(
        _mixed().replace(
            "      flow: authorizationCode\n",
            "      flow: authorizationCode\n      per_user: true\n",
        )
    )

    assert [(d.code, d.element_id) for d in found] == [("invalid-option", "apis.calendar")]
    assert found[0].message == "The key 'per_user' does not suit the scheme 'oauth' (OAuth 2.0)."


def test_the_check_is_an_operation_of_the_api() -> None:
    typo = _load(_security("{ scheme: basicAuth, per_user: true, check: getCurentUser }"))
    other = _load(
        _security("{ scheme: basicAuth, per_user: true, check: searchAndReconsileIssuesUsingJql }")
    )

    assert [(d.code, d.element_id) for d in typo] == [("unknown-reference", "apis.jira")]
    assert "'getCurrentUser'" in (typo[0].hint or "")
    assert [(d.code, d.element_id) for d in other] == [("unknown-reference", "apis.jira")]
    assert other[0].hint == "Add 'searchAndReconsileIssuesUsingJql' to 'operations'."


def test_the_check_has_no_required_values() -> None:
    text = _security("{ scheme: basicAuth, per_user: true, check: getIssue }").replace(
        "    operations: [getCurrentUser, createIssue, addComment]\n",
        "    operations: [getCurrentUser, getIssue, createIssue, addComment]\n",
    )
    found = _load(text)

    assert [(d.code, d.element_id) for d in found] == [("unsuitable-operation", "apis.jira")]
    assert found[0].message == (
        "The check 'getIssue' has the required parameter 'issueIdOrKey', but the app calls it "
        "without values."
    )


def test_the_credentials_of_each_user_need_the_sign_in() -> None:
    start, end = TEXT.index("auth:\n"), TEXT.index("entities:\n")
    text = TEXT[:start] + TEXT[end:]
    text = text.replace("    user: owner\n", "")
    found = [d for d in _load(text) if d.element_id == "apis.jira"]

    assert [d.code for d in found] == ["unsuitable-security"]
    assert found[0].message == (
        "'per_user' calls the API in the name of a user, so the app needs the sign-in of the "
        "users ('auth')."
    )
    assert found[0].hint == "Add the section 'auth', or remove 'per_user'."


def test_a_job_that_calls_the_api_names_the_user() -> None:
    assert _codes(TEXT.replace("    user: owner\n", "")) == [
        ("missing-key", "jobs.file_open_tickets")
    ]


def test_a_page_cannot_use_the_path_of_the_connections() -> None:
    text = TEXT.replace("path: /tickets", "path: /connections")

    found = _load(text)

    assert [(d.code, d.element_id) for d in found] == [("duplicate-name", "pages.tickets")]
    assert found[0].message == "The path '/connections' is the connections page of the apps."


@pytest.mark.parametrize("binding", ["fastapi", "nextjs", "react"])
def test_the_fixture_generates_with_each_binding_and_valid_traces(
    binding: str, tmp_path: Path
) -> None:
    definition = load_definition(FIXTURE)
    write_result(generate(definition, find_binding(binding)), tmp_path, binding)

    report = check_traces(definition, tmp_path)

    assert report.invalid == []


def test_the_fastapi_app_keeps_and_checks_the_credentials(fastapi: dict[str, str]) -> None:
    for path, content in fastapi.items():
        if path.endswith(".py"):
            ast.parse(content, path)
    connections = fastapi["app/core/connections.py"]

    assert 'BASIC_APIS = frozenset({"jira"})' in connections
    assert 'check=("GET", "/rest/api/3/myself"),' in connections
    assert "class UserCredentials:" in connections
    assert "class ConnectionCredentials(BaseModel):" in connections
    assert 'operation_id="connect_jira"' in connections
    # No authorization code flow: no OAuth 2.0 client and no public URL.
    assert "oauth_app" not in connections
    assert "/start" not in connections
    assert "public_url" not in fastapi["app/core/config.py"]
    assert "PUBLIC_URL" not in fastapi[".env.example"]
    migration = fastapi["migrations/versions/0001_schema.py"]
    assert 'sa.Column("username", sa.String(length=320), nullable=True),' in migration
    assert 'sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),' in migration


def test_the_fastapi_client_sends_the_credentials_of_the_user(fastapi: dict[str, str]) -> None:
    client = fastapi["app/integrations/jira/client.py"]

    assert "from app.core.connections import UserCredentials, require_connection" in client
    assert '    scheme = "Basic"\n' in client
    assert 'token = UserCredentials(settings, "jira", sessions, user_id)' in client
    assert 'f"{self.scheme} {token}"' in fastapi["app/integrations/http.py"]
    assert '"Basic user-token"' in fastapi["tests/integrations/test_jira.py"]


def test_the_fastapi_tests_cover_the_credentials(fastapi: dict[str, str]) -> None:
    assert "tests/test_connections.py" not in fastapi
    tests = fastapi["tests/test_credentials.py"]

    for name in (
        "test_a_user_connects_an_account_with_a_user_name_and_a_password",
        "test_credentials_that_the_api_does_not_accept_give_422",
        "test_an_answer_with_the_status_401_rejects_the_connection",
        "test_a_user_deletes_a_connection",
    ):
        assert f"async def {name}(" in tests


def test_the_nextjs_app_keeps_and_checks_the_credentials(nextjs: dict[str, str]) -> None:
    connections = nextjs["src/shared/auth/connections.ts"]

    assert "export class UserCredentials implements TokenSource {" in connections
    assert "export async function connectWithCredentials(" in connections
    assert "Authorization: basicAuthorization(username, password)" in connections
    assert (
        "export async function connectWithCredentialsAction("
        in (nextjs["src/shared/auth/connection-actions.ts"])
    )
    schema = nextjs["src/shared/db/schema/api-connections.ts"]
    assert 'username: varchar("username", { length: 320 }),' in schema
    assert 'rejectedAt: timestamp("rejected_at", { withTimezone: true }),' in schema
    client = nextjs["src/shared/api/jira/client.ts"]
    assert 'scheme: "Basic",' in client
    assert 'token: new UserCredentials("jira", userId),' in client
    # No authorization code flow: no routes of the flow and no public URL.
    assert [path for path in nextjs if path.startswith("app/connections/")] == [
        "app/connections/page.tsx"
    ]
    assert "PUBLIC_URL" not in nextjs[".env.example"]


def test_the_page_has_the_form_of_the_credentials(nextjs: dict[str, str]) -> None:
    page = nextjs["src/features/connections/ui/connections-page.tsx"]

    assert "function CredentialsForm(" in page
    assert 'autoComplete="username"' in page
    assert 'type="password"' in page
    assert "Connected as ${connection.username" in page
    assert "The API did not accept the credentials. Enter new credentials." in page
    assert re.search(r"\bconnectAccount\b", page) is None


def test_the_react_app_with_mock_data_keeps_only_the_user_name() -> None:
    result = generate(load_definition(FIXTURE), find_binding("react"))
    files = _files(result)

    auth = files["src/shared/auth/index.ts"]
    assert "export async function connectWithCredentials(" in auth
    assert re.search(r"\bconnectAccount\b", auth) is None
    assert "function CredentialsForm(" in files["src/features/connections/ui/connections-page.tsx"]
    [warning] = result.warnings
    assert warning.startswith(
        "The API 'jira' sends the password of each user, and a browser app cannot keep a secret,"
    )


def test_an_app_with_both_kinds_of_connections() -> None:
    definition = load_definition_text(_mixed(), str(FIXTURE))
    assert validate_definition(definition) == []
    fastapi = _files(generate(definition, find_binding("fastapi")))
    nextjs = _files(generate(definition, find_binding("nextjs")))

    connections = fastapi["app/core/connections.py"]
    ast.parse(connections)
    assert 'ApiName = Literal["jira", "calendar"]' in connections
    assert 'FlowApiName = Literal["calendar"]' in connections
    assert "tests/test_connections.py" in fastapi
    assert "tests/test_credentials.py" in fastapi
    assert "PUBLIC_URL" in fastapi[".env.example"]
    assert "export function isFlowName(" in nextjs["src/shared/auth/connections.ts"]
    assert "app/connections/[api]/start/route.ts" in nextjs
    page = nextjs["src/features/connections/ui/connections-page.tsx"]
    assert 'connection.kind === "basic" ? (' in page
    assert "change(connection, connectAccount)" in page
