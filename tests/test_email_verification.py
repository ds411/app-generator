"""The verification of the email address of a new user: `auth.sign_up.verify_email` (ADR 0023)."""

import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from appgen.bindings import fastapi
from appgen.cli import app
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.gen.generator import generate

FIXTURE = Path(__file__).parent / "fixtures" / "account-security.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Person:
        fields:
          email: { type: email, required: true, unique: true }
          name: { type: string, required: true }
    pages:
      people: { path: /people, title: People }
    auth:
      user_entity: Person
      username_field: email
      sign_up:
        fields: [email, name]
        verify_email: true
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_the_verification_is_a_flag_or_a_mapping_and_off_by_default() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.auth is not None and definition.auth.sign_up is not None
    verify = definition.auth.sign_up.verify_email
    assert verify is not None and verify.token_minutes == 1440
    assert definition.find("auth.sign_up.verify_email") is verify
    assert definition.address_field() == "email"
    text = BASE.replace("verify_email: true", "verify_email: { token_minutes: 30 }")
    mapping = load_definition_text(text, "app.yaml")
    assert mapping.auth is not None and mapping.auth.sign_up is not None
    assert mapping.auth.sign_up.verify_email is not None
    assert mapping.auth.sign_up.verify_email.token_minutes == 30
    without = BASE.replace("    verify_email: true\n", "")
    for text in (BASE.replace("verify_email: true", "verify_email: false"), without):
        off = load_definition_text(text, "app.yaml")
        assert off.auth is not None and off.auth.sign_up is not None
        assert off.auth.sign_up.verify_email is None


def test_the_time_of_a_link_has_limits() -> None:
    with pytest.raises(DefinitionError, match="less than or equal to 10080"):
        text = BASE.replace("verify_email: true", "verify_email: { token_minutes: 20000 }")
        load_definition_text(text, "app.yaml")


def test_the_verification_needs_a_required_email_field_for_the_address() -> None:
    text = BASE.replace("type: email, required", "type: string, required")
    assert codes(text) == [("unsuitable-field", "auth.sign_up.verify_email")]
    # Another required email field than the user name gives the address.
    other = text.replace(
        "      name: { type: string, required: true }\n",
        "      name: { type: string, required: true }\n"
        "      mail: { type: email, required: true }\n",
    ).replace("fields: [email, name]", "fields: [email, name, mail]")
    assert codes(other) == []
    assert load_definition_text(other, "app.yaml").address_field() == "mail"
    optional = other.replace("mail: { type: email, required: true }", "mail: { type: email }")
    assert codes(optional.replace(", mail]", "]")) == [
        ("unsuitable-field", "auth.sign_up.verify_email")
    ]


def test_no_page_takes_the_path_of_the_verification_page() -> None:
    text = BASE.replace("path: /people", "path: /verify-email")
    assert codes(text) == [("duplicate-name", "pages.people")]
    assert codes(text.replace("    verify_email: true\n", "")) == []


def fastapi_files(text: str | None = None) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml") if text else load_definition(FIXTURE)
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_the_fastapi_sign_up_sends_a_link_and_the_sign_in_waits_for_it() -> None:
    files = fastapi_files()
    auth = files["app/core/auth.py"]
    assert "VERIFY_SECONDS = 7200\n" in auth
    # The sign-up gives 202 without a token, and a sign-in before the link gives 403.
    assert '    "/sign-up", status_code=202, responses=problem_responses(409, 422)' in auth
    assert ") -> VerificationRequested:" in auth
    assert "email_verified_at=null()" in auth
    sign_in = "    if credential.email_verified_at is None:\n        raise ProblemError(403, t("
    assert sign_in in auth
    assert '    "/verify-email",\n    status_code=202,' in auth
    assert '    "/verify-email/confirm",\n    status_code=204,' in auth
    # The token has its own purpose and the tag of the address.
    assert 'return sign(key, "email-verification", payload)' in auth
    assert "user.id, user.email, expires)" in auth
    # The users of the administrator and the users that exist are verified.
    assert "DateTime(timezone=True), server_default=func.now()" in auth
    migration = files["migrations/versions/0001_schema.py"]
    assert '            "email_verified_at",\n' in migration
    assert "            server_default=sa.func.now(),\n" in migration
    # A reset link verifies the address too, and a provider removes an unverified password.
    assert "credential.email_verified_at = datetime.now(UTC)" in auth
    providers = files["app/core/providers.py"]
    assert "await remove_unverified_password(session, user)" in providers
    config = files["app/core/config.py"]
    assert 'email_verify_url: str = "http://localhost:5173/verify-email"' in config
    assert "EMAIL_VERIFY_URL=http://localhost:5173/verify-email" in files[".env.example"]
    config_env = files["deploy/kubernetes/config.env"]
    assert "EMAIL_VERIFY_URL=https://app.example.com/verify-email" in config_env
    tests = files["tests/test_auth.py"]
    assert "async def test_a_user_who_is_not_verified_cannot_sign_in(" in tests
    assert "async def test_a_failed_delivery_rolls_back_the_sign_up(" in tests
    assert "async def test_a_reset_link_verifies_the_email_address(" in tests
    assert "_removes_a_password_that_is_not_verified(" in files["tests/test_providers.py"]


def test_one_delivery_hook_sends_the_messages_of_both_kinds() -> None:
    files = fastapi_files()
    messages = files["app/core/messages.py"]
    assert 'type MessageKind = Literal["password-reset", "email-verification"]' in messages
    assert "def email_verification_message(user: Member, link: str) -> Message:" in messages
    assert '        t("Open the link to confirm the email address of your new account."),' in (
        messages
    )
    # The address is the email field, not the user name.
    assert "    to = user.email\n" in messages
    hook = files["app/core/messages_ext.py"]
    assert "# @trace:gap auth.password_reset file\n" in hook
    assert "# @trace:gap auth.sign_up.verify_email file\n" in hook
    assert "app/core/password_reset_ext.py" not in files


def test_without_the_verification_the_sign_up_gives_a_token() -> None:
    text = FIXTURE.read_text().replace("    verify_email: { token_minutes: 120 }\n", "")
    files = fastapi_files(text)
    auth = files["app/core/auth.py"]
    assert "email_verified_at" not in auth
    assert '    "/sign-up", status_code=201,' in auth
    assert "email_verified_at" not in files["migrations/versions/0001_schema.py"]
    assert "EMAIL_VERIFY_URL" not in files[".env.example"]
    assert "remove_unverified_password" not in files["app/core/providers.py"]
    assert "# @trace:gap auth.sign_up.verify_email" not in files["app/core/messages_ext.py"]


def test_the_check_reports_the_delivery_as_an_open_gap_of_both_elements(tmp_path: Path) -> None:
    runner = CliRunner()
    args = ["generate", str(FIXTURE), "-b", "fastapi", "-o", str(tmp_path)]
    generated = runner.invoke(app, args)
    assert generated.exit_code == 0, generated.output
    result = runner.invoke(app, ["check", str(FIXTURE), str(tmp_path), "-f", "json"])
    report = json.loads(result.output)
    gaps = sorted(g["id"] for g in report["gaps"])
    assert gaps == ["auth.password_reset", "auth.sign_up.verify_email"]
