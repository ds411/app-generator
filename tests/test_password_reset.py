"""The reset of a forgotten password: `auth.password_reset` and the FastAPI app (ADR 0017)."""

import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from appgen.bindings import fastapi
from appgen.cli import app
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.gen.generator import generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Person:
        fields:
          email: { type: email, required: true, unique: true }
    pages:
      people: { path: /people, title: People }
    auth:
      user_entity: Person
      username_field: email
      password_reset: {}
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_a_password_reset_is_valid_and_its_link_is_valid_for_an_hour() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.auth is not None and definition.auth.password_reset is not None
    assert definition.auth.password_reset.token_minutes == 60
    assert definition.find("auth.password_reset") is definition.auth.password_reset
    without = load_definition_text(BASE.replace("  password_reset: {}\n", ""), "app.yaml")
    assert without.auth is not None and without.auth.password_reset is None


def test_the_time_of_a_link_has_limits() -> None:
    with pytest.raises(DefinitionError, match="greater than or equal to 5"):
        load_definition_text(BASE.replace("{}", "{ token_minutes: 1 }"), "app.yaml")


@pytest.mark.parametrize("path", ["/forgot-password", "/reset-password"])
def test_no_page_takes_a_path_of_the_reset_pages(path: str) -> None:
    assert codes(BASE.replace("path: /people", f"path: {path}")) == [
        ("duplicate-name", "pages.people")
    ]
    assert (
        codes(BASE.replace("path: /people", f"path: {path}").replace("  password_reset: {}\n", ""))
        == []
    )


def test_the_fastapi_app_has_the_reset_endpoints_and_a_delivery_hook() -> None:
    definition = load_definition(EXAMPLE)
    result = generate(definition, fastapi.BINDING)
    files = {f.path: f for f in result.files}
    auth = files["app/core/auth.py"].content
    assert "RESET_SECONDS = 1800\n" in auth
    assert '    "/password-reset",\n    status_code=202,' in auth
    assert '    "/password-reset/confirm",\n    status_code=204,' in auth
    assert "from app.core.password_reset_ext import deliver_password_reset\n" in auth
    hook = files["app/core/password_reset_ext.py"]
    assert hook.kind == "extension"
    assert "# @trace:gap auth.password_reset file\n" in hook.content
    assert '    raise NotImplementedError("auth.password_reset")\n' in hook.content
    config = files["app/core/config.py"].content
    assert '    environment: Literal["development", "production"] = "production"\n' in config
    assert "async def test_an_expired_reset_token_gives_400(" in files["tests/test_auth.py"].content


def test_the_check_reports_the_delivery_as_an_open_gap(tmp_path: Path) -> None:
    runner = CliRunner()
    generated = runner.invoke(app, ["generate", str(EXAMPLE), "-b", "fastapi", "-o", str(tmp_path)])
    assert generated.exit_code == 0, generated.output
    result = runner.invoke(app, ["check", str(EXAMPLE), str(tmp_path), "-f", "json"])
    report = json.loads(result.output)
    gaps = [g["id"] for g in report["gaps"]]
    assert "auth.password_reset" in gaps
