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
          name: { type: string }
      Task:
        fields:
          title: { type: string, required: true }
    operations:
      list_tasks: { kind: list, entity: Task }
    pages:
      tasks: { path: /tasks, title: Tasks }
    auth:
      user_entity: Person
      username_field: email
      public_pages: [tasks]
      public_operations: [list_tasks]
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_an_auth_section_is_valid() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.auth is not None
    assert definition.auth.session_hours == 8
    assert definition.find("auth") is definition.auth


def test_the_user_name_is_a_required_unique_text_field() -> None:
    assert codes(BASE.replace("username_field: email", "username_field: name")) == [
        ("unsuitable-field", "auth")
    ]
    assert codes(BASE.replace("user_entity: Person", "user_entity: User")) == [
        ("unknown-reference", "auth")
    ]


def test_the_public_parts_exist_and_no_page_takes_the_sign_in_path() -> None:
    text = BASE.replace("public_pages: [tasks]", "public_pages: [task]").replace(
        "path: /tasks", "path: /sign-in"
    )
    assert codes(text) == [("duplicate-name", "pages.tasks"), ("unknown-reference", "auth")]


def test_each_binding_has_a_sign_in_and_protects_its_parts() -> None:
    definition = load_definition(EXAMPLE)
    for binding in (fastapi.BINDING, nextjs.BINDING, react.BINDING):
        result = generate(definition, binding)
        assert not [g for g in result.gaps if g.kind == "auth"]
    api = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    assert "app/core/auth.py" in api
    assert "tests/test_auth.py" in api
    router = api["app/features/bookings/router.py"]
    assert "router.include_router(list_bookings.router, dependencies=[Depends(check_access)])" in (
        router
    )
    assert "router.include_router(list_rooms.router)\n" in api["app/features/rooms/router.py"]
    web = {f.path: f.content for f in generate(definition, nextjs.BINDING).files}
    assert "app/sign-in/page.tsx" in web
    assert 'await requirePage("bookings", "/bookings");' in web["app/(app-shell)/bookings/page.tsx"]
    assert "requirePageUser" not in web["app/(app-shell)/rooms/page.tsx"]
    assert ", { public: true });" in web["src/entities/room/api/room-actions.ts"]
    spa = {f.path: f.content for f in generate(definition, react.BINDING).files}
    assert (
        '<RequireAuth page="bookings"><BookingsPage /></RequireAuth>' in spa["src/app/router.tsx"]
    )
    assert "element: <RoomsPage /> }" in spa["src/app/router.tsx"]
