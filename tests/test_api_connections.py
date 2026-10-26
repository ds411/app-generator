"""APIs with the authorization code flow: the app calls them with the token of a user (ADR 0033)."""

import ast
from pathlib import Path

import pytest

from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.diagnostics import DefinitionError, Diagnostic
from appgen.dsl.openapi import AuthorizationCodeFlow
from appgen.gen import GenerationResult, find_binding, generate
from appgen.gen.render import GenerationError

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "api-connections.yaml"
TEXT = FIXTURE.read_text()


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


@pytest.fixture(scope="module")
def fastapi() -> dict[str, str]:
    return _files(generate(load_definition(FIXTURE), find_binding("fastapi")))


def test_the_fixture_is_valid_and_has_the_authorization_code_flow() -> None:
    definition = load_definition(FIXTURE)

    assert validate_definition(definition) == []
    api = definition.apis["calendar"]
    assert api.oauth_flow == "authorizationCode"
    assert api.user_flow
    document = api.openapi
    assert document is not None
    scheme = document.security_schemes["oauth"]
    assert scheme.supported
    assert scheme.token_url is None
    assert scheme.authorization_code == AuthorizationCodeFlow(
        authorization_url="/oauth/authorize",
        token_url="/oauth/token",
        refresh_url=None,
        scopes=("events:read", "events:write"),
    )


def test_a_scheme_with_only_the_authorization_code_flow_needs_no_flow_key() -> None:
    definition = load_definition_text(
        TEXT.replace("      flow: authorizationCode\n", ""), str(FIXTURE)
    )

    assert validate_definition(definition) == []
    assert definition.apis["calendar"].user_flow


def test_the_flow_must_be_a_flow_of_the_scheme() -> None:
    found = _load(TEXT.replace("flow: authorizationCode", "flow: clientCredentials"))

    assert [(d.code, d.element_id) for d in found] == [("unknown-reference", "apis.calendar")]
    assert "client credentials" in found[0].message
    assert "'authorizationCode'" in (found[0].hint or "")


def test_the_scopes_are_scopes_of_the_authorization_code_flow() -> None:
    found = _load(TEXT.replace("scopes: [events:read]", "scopes: [events:delete]"))

    assert [(d.code, d.element_id) for d in found] == [("unknown-reference", "apis.calendar")]
    assert "authorization code flow" in found[0].message


def test_the_flow_needs_the_sign_in_of_the_users() -> None:
    start, end = TEXT.index("auth:\n"), TEXT.index("entities:\n")
    found = _load(TEXT[:start] + TEXT[end:])

    assert ("unsuitable-security", "apis.calendar") in [(d.code, d.element_id) for d in found]


def test_a_public_operation_cannot_call_the_api_in_the_name_of_a_user() -> None:
    text = TEXT.replace("  sign_up:\n", "  public_operations: [sync_calendar]\n  sign_up:\n")

    found = _load(text)

    assert [(d.code, d.element_id) for d in found] == [
        ("unsuitable-security", "operations.sync_calendar")
    ]


def test_a_job_that_calls_the_api_names_its_user() -> None:
    found = _load(TEXT.replace("    user: owner\n", ""))

    assert [(d.code, d.element_id) for d in found] == [("missing-key", "jobs.nightly_sync")]


def test_the_user_of_a_job_is_a_relation_to_one_user() -> None:
    owner = "      owner: { kind: many_to_one, target: User, required: true, inverse: calendars }\n"
    viewers = owner + "      viewers: { kind: many_to_many, target: User }\n"
    text = TEXT.replace(owner, viewers).replace("user: owner", "user: viewers")

    assert _codes(text) == [("unsuitable-field", "jobs.nightly_sync")]
    assert _codes(TEXT.replace("user: owner", "user: id")) == [
        ("unknown-reference", "jobs.nightly_sync")
    ]


def test_the_flow_key_is_only_for_oauth() -> None:
    text = (ROOT / "tests" / "fixtures" / "secret-api.yaml").read_text()
    text = text.replace("API_KEY }", "API_KEY, flow: authorizationCode }")
    path = ROOT / "tests" / "fixtures" / "secret-api.yaml"

    definition = load_definition_text(text, str(path))

    assert [(d.code, d.element_id) for d in validate_definition(definition)] == [
        ("invalid-option", "apis.exchange_rates")
    ]


def test_the_fastapi_app_keeps_the_tokens_of_the_users(fastapi: dict[str, str]) -> None:
    connections = fastapi["app/core/connections.py"]
    ast.parse(connections)

    assert 'ApiName = Literal["calendar"]' in connections
    assert 'authorization_url="/oauth/authorize"' in connections
    assert 'refresh_url="/oauth/token"' in connections
    assert 'scopes=("events:read",)' in connections
    assert "AESGCM" in connections
    assert '"api_connections"' in fastapi["migrations/versions/0001_schema.py"]
    assert "from app.core.connections import ApiConnection" in fastapi["app/models.py"]
    assert "app.include_router(connections_router)" in fastapi["app/main.py"]
    assert '"cryptography>=' in fastapi["pyproject.toml"]
    assert "public_url: str" in fastapi["app/core/config.py"]
    assert "tests/test_connections.py" in fastapi


def test_the_client_sends_the_token_of_a_user(fastapi: dict[str, str]) -> None:
    client = fastapi["app/integrations/calendar/client.py"]
    http = fastapi["app/integrations/http.py"]

    assert "token: TokenSource | None = None" in client
    assert "def calendar_client_for(" in client
    assert 'await require_connection(session, "calendar", user.id)' in client
    assert "client_secret" not in client
    assert "class TokenSource(Protocol):" in http
    assert "class StaticToken:" in http
    assert "class ClientCredentials:" not in http


def test_the_job_calls_the_api_with_the_token_of_the_owner(fastapi: dict[str, str]) -> None:
    job = fastapi["app/jobs/nightly_sync.py"]
    test = fastapi["tests/jobs/test_nightly_sync.py"]

    assert 'if not await connected(session, "calendar", record.owner_id):' in job
    assert "calendar = calendar_client_for(settings, sessions, record.owner_id)" in job
    assert 'monkeypatch.setattr(nightly_sync, "connected", connected)' in test


def test_an_app_without_the_flow_has_no_connections() -> None:
    definition = load_definition(ROOT / "examples" / "project-tracker" / "app.yaml")

    files = _files(generate(definition, find_binding("fastapi")))

    assert "app/core/connections.py" not in files
    assert "TokenSource" in files["app/integrations/http.py"]
    assert "StaticToken" not in files["app/integrations/http.py"]
    assert "cryptography" not in files["pyproject.toml"]


def test_the_nextjs_binding_does_not_generate_the_flow_yet() -> None:
    with pytest.raises(GenerationError, match="authorization code flow"):
        generate(load_definition(FIXTURE), find_binding("nextjs"))
