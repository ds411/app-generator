"""The sign-up of new users: `auth.sign_up` and the endpoint of the FastAPI app (ADR 0016)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi
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
