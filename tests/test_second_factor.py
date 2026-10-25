"""The second factor of the sign-in: `auth.second_factor` (ADR 0024)."""

import json
from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from appgen.bindings import fastapi
from appgen.cli import app
from appgen.dsl import load_definition, load_definition_text, validate_definition
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
          role: { type: enum, values: [admin, member], required: true, default: member }
    operations:
      list_people: { kind: list, entity: Person }
    pages:
      people: { path: /people, title: People }
    auth:
      user_entity: Person
      username_field: email
      sign_up:
        fields: [email]
      second_factor:
        totp: true
        required_roles: [admin]
    access:
      role_field: role
      roles:
        admin: { operations: ["*"], pages: ["*"] }
        member: { operations: [list_people], pages: [people] }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_a_second_factor_is_valid_and_off_by_default() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.auth is not None and definition.auth.second_factor is not None
    assert definition.auth.second_factor.required_roles == ["admin"]
    assert definition.find("auth.second_factor") is definition.auth.second_factor
    text = BASE.replace("  second_factor:\n    totp: true\n    required_roles: [admin]\n", "")
    without = load_definition_text(text, "app.yaml")
    assert without.auth is not None and without.auth.second_factor is None


def test_the_second_factor_needs_a_method() -> None:
    assert codes(BASE.replace("totp: true", "totp: false")) == [
        ("missing-key", "auth.second_factor")
    ]


def test_the_required_roles_exist_and_need_access() -> None:
    assert codes(BASE.replace("[admin]\n", "[admin, guest]\n")) == [
        ("unknown-reference", "auth.second_factor")
    ]
    text = BASE.split("access:")[0].replace("required_roles: [admin]", "required_roles: []")
    assert codes(text) == []
    assert codes(BASE.split("access:")[0]) == [("invalid-option", "auth.second_factor")]


def test_the_role_of_the_sign_up_needs_the_email_verification() -> None:
    text = BASE.replace("[admin]\n", "[admin, member]\n")
    assert codes(text) == [("invalid-option", "auth.second_factor")]
    verified = text.replace("fields: [email]", "fields: [email]\n    verify_email: true")
    assert codes(verified) == []


def test_the_second_factor_needs_the_sign_in_with_a_password() -> None:
    text = BASE.replace("  sign_up:\n    fields: [email]\n", "").replace(
        "  second_factor:",
        "  password: false\n"
        "  providers:\n"
        "    company:\n"
        "      issuer: https://login.example.com\n"
        "      client_id_env: COMPANY_CLIENT_ID\n"
        "      client_secret_env: COMPANY_CLIENT_SECRET\n"
        "  second_factor:",
    )
    assert codes(text) == [("invalid-option", "auth.second_factor")]


def test_no_page_takes_the_path_of_the_second_factor_page() -> None:
    text = BASE.replace("path: /people", "path: /second-factor")
    assert codes(text) == [("duplicate-name", "pages.people")]


def fastapi_files(text: str | None = None) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml") if text else load_definition(FIXTURE)
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_the_fastapi_sign_in_gives_a_challenge_for_the_second_factor() -> None:
    files = fastapi_files()
    auth = files["app/core/auth.py"]
    assert 'REQUIRED_ROLES = frozenset({"admin"})' in auth
    assert ") -> Token | SecondFactorChallenge:" in auth
    assert "    if credential.totp_enabled_at is not None or second_factor_required(user):" in auth
    assert 'return sign(key, "second-factor", payload)' in auth
    assert "totp_failures: Mapped[int] = mapped_column(Integer, default=0, server_default=" in auth
    migration = files["migrations/versions/0001_schema.py"]
    assert 'sa.Column("totp_secret", sa.String(length=200), nullable=True),' in migration
    assert 'sa.Column("recovery_codes", sa.Text(), nullable=True),' in migration
    assert "app.include_router(second_factor_router)" in files["app/main.py"]


def test_the_fastapi_codes_follow_rfc_6238_without_a_new_package() -> None:
    files = fastapi_files()
    module = files["app/core/second_factor.py"]
    assert 'digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()' in module
    assert "DRIFT_STEPS = 1\n" in module
    assert "def seal_secret(key: bytes, secret: bytes) -> str:" in module
    for path in (
        '"/sign-in/second-factor",',
        '"/second-factor/setup",',
        '"/second-factor/confirm",',
        '"/second-factor/disable",',
    ):
        assert path in module
    assert "pyotp" not in files["pyproject.toml"]
    tests = files["tests/test_second_factor.py"]
    assert "def test_the_codes_follow_rfc_6238() -> None:" in tests
    assert "async def test_each_code_is_valid_one_time(" in tests
    assert "async def test_a_recovery_code_signs_in_one_time(" in tests
    assert "_turns_it_on_at_the_sign_in(" in tests
    assert "async def _disable_second_factor(username: str) -> int:" in files["app/cli.py"]


def test_without_required_roles_the_sign_in_asks_only_users_with_the_factor() -> None:
    text = FIXTURE.read_text().replace("    required_roles: [admin]\n", "")
    files = fastapi_files(text)
    auth = files["app/core/auth.py"]
    assert "REQUIRED_ROLES" not in auth
    assert "    if credential.totp_enabled_at is not None:\n" in auth
    # Only the code step: a test of the factor that is always true fails the type check.
    assert 'return SecondFactorChallenge(challenge=challenge, second_factor="code")' in auth
    assert 'else "setup"' not in auth
    assert "_turns_it_on_at_the_sign_in(" not in files["tests/test_second_factor.py"]


def test_without_the_second_factor_the_app_has_no_second_factor_files() -> None:
    text = (
        FIXTURE.read_text()
        .replace("  second_factor:\n    totp: true\n", "")
        .replace("    required_roles: [admin]\n", "")
    )
    files = fastapi_files(text)
    assert "app/core/second_factor.py" not in files
    assert "tests/test_second_factor.py" not in files
    assert "totp" not in files["app/core/auth.py"]
    assert "disable-second-factor" not in files["app/cli.py"]


def test_the_check_covers_the_second_factor_without_a_gap(tmp_path: Path) -> None:
    runner = CliRunner()
    args = ["generate", str(FIXTURE), "-b", "fastapi", "-o", str(tmp_path)]
    generated = runner.invoke(app, args)
    assert generated.exit_code == 0, generated.output
    result = runner.invoke(app, ["check", str(FIXTURE), str(tmp_path), "-f", "json"])
    report = json.loads(result.output)
    assert "auth.second_factor" not in [g["id"] for g in report["gaps"]]
    assert report["uncovered"] == []
