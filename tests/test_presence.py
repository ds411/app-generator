"""The other users on a record page (ADR 0052): the DSL, the checks, and the apps."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "courses.yaml"
RULES = ROOT / "tests" / "fixtures" / "record-rules.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: school, title: School }
    entities:
      User:
        display_field: name
        fields:
          name: { type: string, required: true }
          email: { type: email, required: true, unique: true }
      Course:
        crud: { views: [table, detail] }
        fields:
          title: { type: string, required: true }
        relations:
          lessons: { kind: one_to_many, target: Lesson, inverse: course }
      Lesson:
        crud: { views: [table, detail], forms: [create, update] }
        live: true
        fields:
          title: { type: string, required: true }
          body: { type: text }
        relations:
          course: { kind: many_to_one, target: Course, inverse: lessons }
    pages:
      lesson:
        path: "{path}"
        title: Lesson
        entity: Lesson
        content: { view: lesson_detail }
        presence: true
      course:
        path: "/courses/{id}"
        title: Course
        entity: Course
        content: { view: course_detail }
    auth:
      user_entity: User
      username_field: email
    """
)


def definition_text(*, path: str = "/lessons/{id}", auth: bool = True, live: bool = True) -> str:
    """Return the base definition with the path of the page, with or without `auth` and `live`."""
    text = BASE.replace("{path}", path)
    if not live:
        text = text.replace("    live: true\n", "", 1)
    return text if auth else text[: text.index("auth:")]


def diagnostics(text: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_detail_page_of_a_live_entity_with_presence_is_valid() -> None:
    assert diagnostics(definition_text()) == []


def test_presence_needs_the_section_auth() -> None:
    found = diagnostics(definition_text(auth=False))

    assert [(code, element) for code, element, _ in found] == [("invalid-option", "pages.lesson")]
    assert "needs the section 'auth'" in found[0][2]


def test_a_public_page_does_not_take_presence() -> None:
    text = definition_text().replace(
        "  username_field: email\n", "  username_field: email\n  public_pages: [lesson]\n"
    )

    found = diagnostics(text)

    assert any("A public page has no signed-in user" in message for _, _, message in found)


def test_presence_needs_a_page_with_a_detail_view() -> None:
    text = definition_text().replace(
        "content: { view: lesson_detail }", "content: { view: lesson_table }"
    )

    found = diagnostics(text.replace('path: "/lessons/{id}"', "path: /lessons"))

    assert [message for _, _, message in found if "presence" in message] == [
        "The page shows the users on one record, so 'presence' needs a page with a detail view."
    ]


@pytest.mark.parametrize("path", ["/lessons/{id}/edit", "/courses/{course}/lessons/{id}"])
def test_the_path_of_a_page_with_presence_has_only_the_id_at_the_end(path: str) -> None:
    found = diagnostics(definition_text(path=path))

    assert any("ends with '/{id}'" in message for _, _, message in found)


def test_presence_needs_a_live_entity() -> None:
    found = diagnostics(definition_text(live=False))

    assert found == [
        (
            "invalid-option",
            "pages.lesson",
            "The users on a record get the changes through the live updates (ADR 0051), so "
            "'presence' needs 'live' on the entity 'Lesson'.",
        )
    ]


def with_api_data(text: str) -> str:
    """Return a definition whose React app uses the FastAPI app (`x-react-data: api`)."""
    return text.replace(
        "app: { name: school, title: School }",
        "app: { name: school, title: School, x-react-data: api }",
        1,
    )


def test_the_fastapi_app_has_the_presence_endpoints_and_keeps_the_users_in_the_broker() -> None:
    files = files_of(definition_text(), fastapi.BINDING)
    presence = files["app/features/lessons/presence.py"]
    assert '@router.put(\n    "/lessons/{id}/presence"' in presence
    assert '@router.delete(\n    "/lessons/{id}/presence"' in presence
    assert 'operation_id="update_lesson_presence"' in presence
    assert 'broker.here("Lesson", record.id, user.id, str(user.name), body.typing)' in presence
    assert "router.include_router(presence.router)" in files["app/features/lessons/router.py"]
    assert "app/features/courses/presence.py" not in files
    live = files["app/core/live.py"]
    assert "class Here:" in live
    assert "PRESENCE_SECONDS = 15" in live
    assert 'type: Literal["open", "created", "changed", "deleted", "reset", "presence"]' in live
    tests = files["tests/test_live.py"]
    assert "async def test_the_users_on_a_page_of_lesson_see_each_other(" in tests
    assert "async def test_the_broker_forgets_a_user_without_a_call(" in tests


def test_the_fastapi_endpoints_need_the_read_operation_of_a_role() -> None:
    role = "      role: { type: enum, values: [admin, member], default: member }\n"
    text = definition_text().replace(
        "    fields:\n      name:", f"    fields:\n{role}      name:", 1
    )
    text += dedent(
        """\
        access:
          role_field: role
          roles:
            admin: { operations: ["*"], pages: ["*"] }
            member: { operations: [read_lesson, list_lessons], pages: [lesson] }
        """
    )
    files = files_of(text, fastapi.BINDING)
    access = files["app/core/access.py"]
    assert '"update_lesson_presence": "read_lesson",' in access
    assert '"delete_lesson_presence": "read_lesson",' in access


def test_the_fastapi_endpoints_read_the_record_with_the_record_rules() -> None:
    definition = load_definition(RULES)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    presence = files["app/features/tasks/presence.py"]
    assert "from app.core.access import RecordScope, check_access, scope_of\n" in presence
    assert "    dependencies=[Depends(check_access)],\n" in presence
    assert "    record = await repository.get(session, id, scope)\n" in presence


def test_the_live_app_without_presence_has_no_presence_code() -> None:
    files = files_of(definition_text().replace("    presence: true\n", ""), fastapi.BINDING)
    live = files["app/core/live.py"]
    assert "Here" not in live
    assert "presence" not in live
    assert "app/features/lessons/presence.py" not in files


def test_the_nextjs_app_has_the_presence_actions_and_the_avatars() -> None:
    files = files_of(definition_text(), nextjs.BINDING)
    actions = files["src/entities/lesson/api/lesson-actions.ts"]
    assert "export async function hereLessonPresenceAction(id: string, typing: boolean)" in actions
    assert "export async function leaveLessonPresenceAction(id: string)" in actions
    assert "lessonPresence" in files["src/entities/lesson/index.ts"]
    live = files["src/shared/db/live.ts"]
    assert "export async function notePresence(" in live
    assert "const PRESENCE_MS = 15_000;" in live
    page = files["src/pages/lesson/ui/lesson-page.tsx"]
    assert '<RecordPresence presence={lessonPresence} id={id ?? ""} />' in page
    assert "<RecordPresence" not in files["src/pages/course/ui/course-page.tsx"]
    component = files["src/features/record-presence/ui/record-presence.tsx"]
    assert "const HEARTBEAT_MS = 5_000;" in component
    assert "`${first} is typing.`" in component
    assert "liveEvents(batched(notifyChange))" in files["src/app/providers/live-updates.tsx"]
    assert "export function watchPresence(" in files["src/shared/lib/live.ts"]


def test_the_react_app_with_mock_data_shows_no_users() -> None:
    files = files_of(definition_text(), react.BINDING)
    assert not [path for path in files if "presence" in path]
    assert "<RecordPresence" not in files["src/pages/lesson/ui/lesson-page.tsx"]


def test_the_react_app_with_the_api_calls_the_presence_endpoints() -> None:
    files = files_of(with_api_data(definition_text()), react.BINDING)
    store = files["src/shared/api/http-store.ts"]
    assert 'this.request("PUT", id, { typing }, "/presence")' in store
    assert 'this.request("DELETE", id, undefined, "/presence")' in store
    assert "lessonApi.presence();" in files["src/entities/lesson/api/lesson-api.ts"]
    assert "<RecordPresence" in files["src/pages/lesson/ui/lesson-page.tsx"]
    assert "liveEvents(batched(notifyChange))" in files["src/app/providers/live-updates.tsx"]


@pytest.mark.parametrize("binding", [fastapi.BINDING, nextjs.BINDING, react.BINDING])
def test_an_app_without_presence_has_no_presence_files(binding: Binding) -> None:
    text = with_api_data(definition_text().replace("    presence: true\n", ""))
    files = files_of(text, binding)
    assert not [path for path in files if "presence" in path]
    assert not [content for content in files.values() if "RecordPresence" in content]


def test_the_course_hub_shows_the_users_on_its_lessons() -> None:
    definition = load_definition(FIXTURE)
    assert validate_definition(definition) == []
    assert definition.pages["lesson_detail"].presence is True
    assert definition.entities["Lesson"].live is not None
