"""The reset of a forgotten password: `auth.password_reset`, the apps, and the pages (ADR 0017)."""

import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from appgen.bindings import fastapi, nextjs, react
from appgen.cli import app
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.gen.binding import Binding
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


def hook_text() -> str:
    """Return the room booking example with the delivery hook, not the delivery by SMTP.

    The emails of the notices need the delivery by SMTP, so the
    notifications have no emails.
    """
    text = EXAMPLE.read_text().replace("  delivery: smtp\n", "")
    return text.replace("    email: true\n", "")


def test_the_fastapi_app_has_the_reset_endpoints_and_a_delivery_hook() -> None:
    definition = load_definition_text(hook_text(), "app.yaml")
    result = generate(definition, fastapi.BINDING)
    files = {f.path: f for f in result.files}
    auth = files["app/core/auth.py"].content
    assert "RESET_SECONDS = 1800\n" in auth
    assert '    "/password-reset",\n    status_code=202,' in auth
    assert '    "/password-reset/confirm",\n    status_code=204,' in auth
    assert "from app.core.messages_ext import deliver_message\n" in auth
    assert "await deliver_message(settings, password_reset_message(user, link))" in auth
    hook = files["app/core/messages_ext.py"]
    assert hook.kind == "extension"
    assert "# @trace:gap auth.password_reset file\n" in hook.content
    assert "async def deliver_message(settings: Settings, message: Message) -> None:" in (
        hook.content
    )
    assert "    raise NotImplementedError(" in hook.content
    assert "def password_reset_message(user: Member, link: str) -> Message:" in (
        files["app/core/messages.py"].content
    )
    config = files["app/core/config.py"].content
    assert '    environment: Literal["development", "production"] = "production"\n' in config
    assert "async def test_an_expired_reset_token_gives_400(" in files["tests/test_auth.py"].content


@pytest.mark.parametrize("binding", ["fastapi", "nextjs"])
def test_the_check_reports_the_delivery_as_an_open_gap(tmp_path: Path, binding: str) -> None:
    source, out = tmp_path / "app.yaml", tmp_path / "out"
    source.write_text(hook_text())
    runner = CliRunner()
    generated = runner.invoke(app, ["generate", str(source), "-b", binding, "-o", str(out)])
    assert generated.exit_code == 0, generated.output
    result = runner.invoke(app, ["check", str(source), str(out), "-f", "json"])
    report = json.loads(result.output)
    gaps = [g["id"] for g in report["gaps"]]
    assert "auth.password_reset" in gaps


def files(binding: Binding, text: str | None = None) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml") if text else load_definition(EXAMPLE)
    return {f.path: f.content for f in generate(definition, binding).files}


def api_text() -> str:
    return EXAMPLE.read_text().replace("app:\n", "app:\n  x-react-data: api\n", 1)


def test_the_nextjs_app_has_the_reset_pages_with_the_token_rules_of_the_api() -> None:
    app = files(nextjs.BINDING, hook_text())
    assert "<ForgotPasswordForm />" in app["app/forgot-password/page.tsx"]
    assert "<ResetPasswordForm token=" in app["app/reset-password/page.tsx"]
    reset = app["src/shared/auth/password-reset.ts"]
    # The same rules as the FastAPI app: a tag of the password hash, an end time, and a prefix.
    assert "export const RESET_SECONDS = 1800;" in reset
    assert "return sign(`password-reset.${body}`);" in reset
    assert "const payload = { sub: userId, exp: expires, pwd: passwordTag(passwordHash) };" in reset
    actions = app["src/shared/auth/actions.ts"]
    message = "passwordResetMessage({ id: user.id, to: user.to }, link)"
    assert f"await deliverMessage(await {message});" in actions
    assert "if (found === null || !(await resetTokenMatches(found))) {" in actions
    assert "await setPassword(found.userId, input.data.newPassword);" in actions
    hook = app["src/shared/auth/messages.ext.ts"]
    assert hook.startswith("// Created by appgen once.")
    assert "// @trace:gap auth.password_reset file" in hook
    assert 'if (process.env.ENVIRONMENT === "development") {' in hook
    assert "src/shared/auth/password-reset.ext.ts" not in app
    assert "PUBLIC_URL=http://localhost:3000" in app[".env.example"]
    sign_in = app["src/features/sign-in/ui/sign-in-form.tsx"]
    assert '<Link href="/forgot-password"' in sign_in
    assert "src/gaps/auth.password_reset.ext.ts" not in app


def test_the_react_app_has_the_reset_pages_only_with_the_api() -> None:
    api = files(react.BINDING, api_text())
    auth = api["src/shared/auth/index.ts"]
    assert 'await apiRequest("POST", "/auth/password-reset", { username });' in auth
    confirm = '"/auth/password-reset/confirm", { token, new_password: newPassword });'
    assert confirm in auth
    router = api["src/app/router.tsx"]
    assert '{ path: "/forgot-password", element: <ForgotPasswordForm /> },' in router
    assert '{ path: "/reset-password", element: <ResetPasswordRoute /> },' in router
    assert "src/features/password-reset/ui/reset-password-form.tsx" in api
    mock = files(react.BINDING)
    assert not [path for path in mock if "password-reset" in path]
    assert "forgot-password" not in mock["src/features/sign-in/ui/sign-in-form.tsx"]
    assert (
        "so an app with mock data has no reset pages. // @trace auth.password_reset"
        in (mock["src/shared/auth/index.ts"])
    )


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=lambda b: b.name)
def test_the_reset_form_checks_the_length_of_the_new_password(binding: Binding) -> None:
    app = files(binding, api_text() if binding is react.BINDING else None)
    form = app["src/features/password-reset/ui/reset-password-form.tsx"]
    assert "const MIN_PASSWORD_LENGTH = 10;" in form
    assert 'autoComplete="new-password"' in form
    assert "await confirmPasswordReset(token, password);" in form
