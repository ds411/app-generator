from pathlib import Path
from textwrap import dedent

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
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
          role: { type: enum, values: [admin, viewer] }
      Task:
        fields:
          title: { type: string, required: true }
    operations:
      list_tasks: { kind: list, entity: Task }
      create_task: { kind: create, entity: Task }
    pages:
      tasks: { path: /tasks, title: Tasks }
    auth:
      user_entity: Person
      username_field: email
    access:
      role_field: role
      roles:
        admin: { label: Admin, operations: ["*"], pages: ["*"] }
        viewer: { label: Viewer, operations: [list_tasks], pages: [tasks] }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_an_access_section_is_valid() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.access is not None
    viewer = definition.access.roles["viewer"]
    assert viewer.allows_operation("list_tasks")
    assert not viewer.allows_operation("create_task")
    assert definition.access.roles["admin"].allows_page("tasks")


def test_access_needs_auth() -> None:
    text = BASE.replace("auth:\n  user_entity: Person\n  username_field: email\n", "")
    assert [c for c, _ in codes(text)] == ["missing-key"]


def test_the_role_field_is_an_enum_and_the_roles_are_its_values() -> None:
    assert codes(BASE.replace("role_field: role", "role_field: email")) == [
        ("unsuitable-field", "access")
    ]
    assert [c for c, _ in codes(BASE.replace("viewer: { label", "guest: { label"))] == [
        "unknown-reference"
    ]


def test_the_operations_and_pages_of_a_role_exist() -> None:
    text = BASE.replace("operations: [list_tasks]", "operations: [list_task]").replace(
        "pages: [tasks]", "pages: [task]"
    )
    assert [c for c, _ in codes(text)] == ["unknown-reference", "unknown-reference"]


def test_each_binding_checks_the_permissions() -> None:
    definition = load_definition(EXAMPLE)
    for binding in (fastapi.BINDING, nextjs.BINDING, react.BINDING):
        result = generate(definition, binding)
        assert not [g for g in result.gaps if g.kind in ("access", "role")]
    api = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    assert "app/core/access.py" in api
    assert "tests/test_access.py" in api
    assert "Depends(check_access)" in api["app/features/bookings/router.py"]
    web = {f.path: f.content for f in generate(definition, nextjs.BINDING).files}
    assert "src/shared/auth/access.ts" in web
    assert "requirePage(" in web["app/(app-shell)/bookings/page.tsx"]
    spa = {f.path: f.content for f in generate(definition, react.BINDING).files}
    assert 'requireOperation("create_room");' in spa["src/entities/room/api/room-api.ts"]
    assert 'page="bookings"' in spa["src/app/router.tsx"]
