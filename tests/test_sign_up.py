"""The sign-up of new users: `auth.sign_up`, the FastAPI endpoint, and the pages (ADR 0016)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
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
          name: { type: string, required: true }
          nickname: { type: string }
          role: { type: enum, values: [admin, viewer], default: viewer }
      Task:
        fields:
          title: { type: string, required: true }
    operations:
      list_tasks: { kind: list, entity: Task }
    auth:
      user_entity: Person
      username_field: email
      sign_up:
        fields: [email, name]
        default_role: viewer
    access:
      role_field: role
      roles:
        admin: { operations: ["*"] }
        viewer: { operations: [list_tasks] }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_a_sign_up_is_valid_and_off_by_default() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.auth is not None and definition.auth.sign_up is not None
    assert definition.find("auth.sign_up") is definition.auth.sign_up
    assert definition.auth.min_password_length == 8
    text = BASE.replace("  sign_up:\n    fields: [email, name]\n    default_role: viewer\n", "")
    assert load_definition_text(text, "app.yaml").auth.sign_up is None  # pyright: ignore[reportOptionalMemberAccess]


def test_the_sign_up_asks_for_each_required_field() -> None:
    assert codes(BASE.replace("fields: [email, name]", "fields: [email]")) == [
        ("missing-key", "auth.sign_up")
    ]
    assert codes(BASE.replace("fields: [email, name]", "fields: [email, name, age]")) == [
        ("unknown-reference", "auth.sign_up")
    ]


def test_a_new_user_cannot_choose_the_role() -> None:
    assert codes(BASE.replace("fields: [email, name]", "fields: [email, name, role]")) == [
        ("unsuitable-field", "auth.sign_up")
    ]


def test_the_sign_up_form_has_a_widget_for_each_field() -> None:
    text = BASE.replace("\n      role: {", "\n      settings: { type: json }\n      role: {")
    text = text.replace("fields: [email, name]", "fields: [email, name, settings]")
    assert codes(text) == [("unsuitable-field", "auth.sign_up")]


def test_the_default_role_exists() -> None:
    assert codes(BASE.replace("default_role: viewer", "default_role: guest")) == [
        ("unknown-reference", "auth.sign_up")
    ]
    no_default = BASE.replace(", default: viewer", "").replace("    default_role: viewer\n", "")
    assert codes(no_default) == [("missing-key", "auth.sign_up")]
    without_access = BASE.split("access:")[0]
    assert codes(without_access) == [("invalid-option", "auth.sign_up")]


def test_the_minimum_password_length_has_a_lower_limit() -> None:
    text = BASE.replace("  sign_up:", "  min_password_length: 6\n  sign_up:")
    with pytest.raises(DefinitionError, match="greater than or equal to 8"):
        load_definition_text(text, "app.yaml")


def test_no_page_takes_the_sign_up_path() -> None:
    text = BASE.replace("auth:", "pages:\n  join: { path: /sign-up, title: Join }\nauth:")
    assert codes(text) == [("duplicate-name", "pages.join")]


def test_the_fastapi_app_has_a_sign_up_endpoint() -> None:
    definition = load_definition(EXAMPLE)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    auth = files["app/core/auth.py"]
    assert '    "/sign-up", status_code=201, responses=problem_responses(409, 422)' in auth
    assert '    values["role"] = "member"\n' in auth
    assert "    await flush(session)\n" in auth
    assert "MIN_PASSWORD_LENGTH = 10\n" in auth
    schemas = files["app/features/members/schemas.py"]
    sign_up = schemas.split("class MemberSignUp(InputModel):")[1]
    assert "    team: MemberTeam | None = None\n" in sign_up
    assert "role" not in sign_up
    assert "    password: str = Field(min_length=10, max_length=200)\n" in sign_up
    assert (
        "async def test_a_sign_up_with_a_user_name_that_exists_gives_409("
        in files["tests/test_auth.py"]
    )


def test_the_fastapi_app_of_roles_without_a_sign_up_has_no_sign_up_tests() -> None:
    text = BASE.replace("  sign_up:\n    fields: [email, name]\n    default_role: viewer\n", "")
    definition = load_definition_text(text, "app.yaml")
    assert definition.auth is not None and definition.auth.sign_up is None
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    assert "/sign-up" not in files["app/core/auth.py"]
    tests = files["tests/test_auth.py"]
    assert "async def test_a_protected_endpoint_needs_a_signed_in_user(" in tests
    assert "sign_up" not in tests


def files(binding: Binding, text: str | None = None) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml") if text else load_definition(EXAMPLE)
    return {f.path: f.content for f in generate(definition, binding).files}


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=lambda b: b.name)
def test_the_front_ends_have_a_sign_up_page(binding: Binding) -> None:
    app = files(binding)
    form = app["src/features/sign-up/ui/sign-up-form.tsx"]
    # The fields of the sign-up, with the widgets of the entity fields, and a password.
    assert '<Input id="sign-up-email" type="email"' in form
    assert '<OptionSelect id="sign-up-team" options={TEAM_OPTIONS}' in form
    assert 'autoComplete="new-password"' in form
    assert "window.location.assign(next);" in form
    schema = app["src/features/sign-up/model/schema.ts"]
    assert "export const MIN_PASSWORD_LENGTH = 10;" in schema
    assert "memberInputSchema.pick({ name: true, email: true, team: true }).extend({" in schema
    sign_in = app["src/features/sign-in/ui/sign-in-form.tsx"]
    assert "<Link href={`/sign-up?next=${encodeURIComponent(next)}`}" in sign_in
    assert "src/gaps/auth.sign_up.ext.ts" not in app


def test_the_nextjs_sign_up_adds_the_user_and_the_password_in_one_transaction() -> None:
    app = files(nextjs.BINDING)
    action = app["src/features/sign-up/api/sign-up-action.ts"]
    assert (
        'await memberRepository.create({ ...fields, role: "member" }, async (tx, record) => {'
        in (action)
    )
    assert "await tx.insert(credentialsTable).values(" in action
    assert "await startSession(user.id);" in action
    assert "{ public: true, changes: true }," in action
    repository = app["src/shared/db/repository.ts"]
    assert "      await then?.(tx, record as T);\n" in repository
    assert "<SignUpForm next=" in app["app/sign-up/page.tsx"]
    assert "  await startSession(userId);\n" in app["src/shared/auth/actions.ts"]


def test_the_react_sign_up_calls_the_api_or_adds_a_mock_user() -> None:
    mock = files(react.BINDING)
    assert (
        "await addMockUser(input.email, input.password);"
        in (mock["src/features/sign-up/api/sign-up.ts"])
    )
    auth = mock["src/shared/auth/index.ts"]
    assert 'const SIGN_UPS_KEY = "room-booking-sign-ups";' in auth
    assert 'role: "member", passwordHash: await passwordHash(password) };' in auth
    assert "if (!user || !(await passwordMatches(user, password))) {" in auth
    assert '{ path: "/sign-up", element: <SignUpRoute /> },' in mock["src/app/router.tsx"]
    text = EXAMPLE.read_text().replace("app:\n", "app:\n  x-react-data: api\n", 1)
    api = files(react.BINDING, text)
    sign_up = api["src/features/sign-up/api/sign-up.ts"]
    assert 'await apiRequest("POST", "/auth/sign-up", {' in sign_up
    assert "    team: input.team,\n" in sign_up
    assert "await startSession(token.access_token);" in sign_up
    assert (
        "export async function startSession(token: string): Promise<void> {"
        in (api["src/shared/auth/index.ts"])
    )


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=lambda b: b.name)
def test_without_a_sign_up_the_front_ends_have_no_sign_up_page(binding: Binding) -> None:
    sign_up = "  sign_up:\n    fields: [name, email, team]\n    default_role: member\n"
    text = EXAMPLE.read_text().replace(sign_up, "")
    app = files(binding, text)
    assert not [path for path in app if "sign-up" in path]
    assert "/sign-up" not in app["src/features/sign-in/ui/sign-in-form.tsx"]


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=lambda b: b.name)
def test_an_app_without_forms_gets_the_runtime_files_of_the_sign_up_form(binding: Binding) -> None:
    app = files(binding, BASE)
    for path in ("src/shared/lib/form.ts", "src/shared/ui/field.tsx", "src/shared/ui/input.tsx"):
        assert path in app
    assert "src/entities/person/model/schema.ts" in app
    assert (
        "personInputSchema.pick({ email: true, name: true })"
        in (app["src/features/sign-up/model/schema.ts"])
    )
