"""The sign-in with OpenID Connect providers: `auth.providers` and `auth.password` (ADR 0020)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "room-booking" / "app.yaml"
PROVIDERS_ONLY = ROOT / "tests" / "fixtures" / "provider-sign-in.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Person:
        fields:
          email: { type: email, required: true, unique: true }
          name: { type: string, required: true }
          role: { type: enum, values: [admin, viewer] }
    auth:
      user_entity: Person
      username_field: email
      providers:
        company:
          issuer: https://login.example.com
          client_id_env: COMPANY_CLIENT_ID
          client_secret_env: COMPANY_CLIENT_SECRET
    access:
      role_field: role
      roles:
        admin: { operations: ["*"] }
        viewer: { operations: [] }
    """
)
CREATES = "      create_users: true\n      default_role: viewer\n      claims: { name: name }\n"


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def with_provider(lines: str) -> str:
    """Return the base definition with more keys for the provider `company`."""
    return BASE.replace(
        "      client_secret_env: COMPANY_CLIENT_SECRET\n",
        "      client_secret_env: COMPANY_CLIENT_SECRET\n" + lines,
    )


def test_a_provider_is_valid_and_has_defaults() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.auth is not None and definition.auth.password
    provider = definition.auth.providers["company"]
    assert definition.find("auth.providers.company") is provider
    assert provider.scopes == ["openid", "email", "profile"]
    assert provider.username_claim == "email"
    assert not provider.create_users
    assert codes(with_provider(CREATES)) == []


def test_the_issuer_is_an_https_url() -> None:
    with pytest.raises(DefinitionError, match="does not match the pattern"):
        load_definition_text(BASE.replace("https://login", "http://login"), "app.yaml")


def test_each_environment_variable_has_one_use() -> None:
    text = BASE.replace("COMPANY_CLIENT_SECRET", "COMPANY_CLIENT_ID")
    assert codes(text) == [("duplicate-name", "auth.providers.company")]
    # The setting of the issuer has the variable COMPANY_ISSUER.
    text = BASE.replace("COMPANY_CLIENT_SECRET", "COMPANY_ISSUER")
    assert codes(text) == [("duplicate-name", "auth.providers.company")]
    text = BASE.replace("COMPANY_CLIENT_SECRET", "AUTH_SECRET")
    assert codes(text) == [("reserved-name", "auth.providers.company")]


def test_the_scopes_include_openid() -> None:
    assert codes(with_provider("      scopes: [email]\n")) == [
        ("invalid-value", "auth.providers.company")
    ]


def test_the_options_of_new_users_need_create_users() -> None:
    lines = "      default_role: viewer\n      claims: { name: name }\n"
    assert codes(with_provider(lines)) == [
        ("invalid-option", "auth.providers.company"),
        ("invalid-option", "auth.providers.company"),
    ]


def test_a_new_user_gets_each_required_field_and_a_role() -> None:
    assert codes(with_provider(CREATES.replace("      claims: { name: name }\n", ""))) == [
        ("missing-key", "auth.providers.company")
    ]
    assert codes(with_provider(CREATES.replace("      default_role: viewer\n", ""))) == [
        ("missing-key", "auth.providers.company")
    ]
    assert codes(with_provider(CREATES.replace("viewer", "guest"))) == [
        ("unknown-reference", "auth.providers.company")
    ]
    for claims in ("{ name: name, role: groups }", "{ name: name, email: upn }"):
        lines = CREATES.replace("{ name: name }", claims)
        assert codes(with_provider(lines)) == [("unsuitable-field", "auth.providers.company")]


def test_the_sign_in_without_a_password_needs_a_provider() -> None:
    off = BASE.replace("  username_field: email\n", "  username_field: email\n  password: false\n")
    assert codes(off) == []
    without = off.split("  providers:")[0] + "access:" + off.split("access:")[1]
    assert codes(without) == [("missing-key", "auth")]
    sign_up = off.replace(
        "  password: false\n", "  password: false\n  sign_up: { fields: [email, name] }\n"
    )
    assert ("invalid-option", "auth.sign_up") in codes(sign_up)


def test_the_fastapi_app_has_the_flow_of_each_provider() -> None:
    files = {f.path: f.content for f in generate(load_definition(EXAMPLE), fastapi.BINDING).files}
    providers = files["app/core/providers.py"]
    assert 'ProviderName = Literal["company"]\n' in providers
    assert '            default_role="member",\n' in providers
    assert '            claims=(("name", "name"),),\n' in providers
    assert '"code_challenge_method": "S256",' in providers
    assert 'options={"require": ["aud", "exp", "iat", "iss", "nonce", "sub"]},' in providers
    config = files["app/core/config.py"]
    assert '    company_issuer: str = "https://login.example.com"\n' in config
    assert 'Field(default="", validation_alias="COMPANY_CLIENT_ID")' in config
    assert '    "pyjwt[crypto]>=2.15",\n' in files["pyproject.toml"]
    assert "    app.include_router(providers_router)\n" in files["app/main.py"]
    assert "COMPANY_CLIENT_SECRET=\n" in files["deploy/kubernetes/secret.example.env"]
    tests = files["tests/test_providers.py"]
    assert "async def test_a_first_sign_in_with_the_provider_company_makes_a_user(" in tests
    assert "async def test_an_id_token_that_is_not_valid_gives_401(" in tests
    # The sign-in with a password stays.
    assert '@router.post("/sign-in"' in files["app/core/auth.py"]


def test_the_fastapi_app_without_a_password_has_no_password_parts() -> None:
    definition = load_definition(PROVIDERS_ONLY)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    auth = files["app/core/auth.py"]
    assert "/sign-in" not in auth
    assert "class Credential" not in auth
    assert "hash_password" not in auth
    assert "app/cli.py" not in files
    assert "credentials" not in files["migrations/versions/0001_schema.py"]
    assert "Credential" not in files["app/models.py"]
    assert 'ProviderName = Literal["company", "partner"]\n' in files["app/core/providers.py"]
    tests = files["tests/test_providers.py"]
    assert "async def test_a_first_sign_in_with_the_provider_company_makes_a_user(" in tests
    assert "set_password" not in files["tests/test_auth.py"]
