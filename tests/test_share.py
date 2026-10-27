"""The secret links of the records (ADR 0049): the DSL, the checks, and the apps."""

import re
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "courses.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: school, title: School }
    entities:
      User:
        fields:
          email: { type: email, required: true, unique: true }
      Course:
        crud: { views: [table, detail] }
        fields:
          title: { type: string, required: true }
        relations:
          lessons: { kind: one_to_many, target: Lesson, inverse: course }
      Lesson:
        crud: { views: [table, detail], forms: [create, update] }
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
        share: true
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


def definition_text(*, path: str = "/lessons/{id}", auth: bool = True) -> str:
    """Return the base definition with the path of the shared page, with or without `auth`."""
    text = BASE.replace("{path}", path)
    return text if auth else text[: text.index("auth:")]


def diagnostics(text: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_detail_page_with_share_is_valid() -> None:
    assert diagnostics(definition_text()) == []


def test_the_shared_path_puts_the_token_in_the_place_of_the_id() -> None:
    definition = load_definition_text(definition_text(path="/courses/lessons/{id}"), "app.yaml")
    assert definition.pages["lesson"].shared_path == "/shared/courses/lessons/{token}"


def test_share_needs_the_section_auth() -> None:
    found = diagnostics(definition_text(auth=False))
    assert [(code, element) for code, element, message in found if "'auth'" in message] == [
        ("invalid-option", "pages.lesson")
    ]


def test_a_public_page_does_not_take_share() -> None:
    text = definition_text().replace(
        "username_field: email", "username_field: email\n  public_pages: [lesson]"
    )
    assert [code for code, _, message in diagnostics(text) if "public page" in message] == [
        "invalid-option"
    ]


def test_share_needs_a_page_with_a_detail_view() -> None:
    text = definition_text().replace(
        "content: { view: lesson_detail }", "content: { view: lesson_table }"
    )
    found = diagnostics(text)
    assert [code for code, _, message in found if "detail view" in message] == ["invalid-option"]


@pytest.mark.parametrize("path", ["/lessons/{id}/edit", "/courses/{course_id}/lessons/{id}"])
def test_the_path_of_a_shared_page_has_only_the_id_at_the_end(path: str) -> None:
    found = diagnostics(definition_text(path=path))
    assert [code for code, _, message in found if "token in the place" in message] == [
        "invalid-option"
    ]


def test_share_needs_an_update_operation() -> None:
    text = definition_text().replace("forms: [create, update]", "forms: [create]")
    text = text.replace(
        "crud: { views: [table, detail], forms: [create] }",
        "crud: { operations: [create, read, list, delete], views: [table, detail] }",
    )
    found = diagnostics(text)
    assert [code for code, _, message in found if "update operation" in message] == [
        "invalid-option"
    ]


def test_an_entity_has_one_shared_page_at_most() -> None:
    text = definition_text().replace(
        "  course:\n    path:",
        "  lesson_copy:\n"
        '    path: "/lesson-copies/{id}"\n'
        "    title: Lesson\n"
        "    entity: Lesson\n"
        "    content: { view: lesson_detail }\n"
        "    share: true\n"
        "  course:\n    path:",
    )
    found = diagnostics(text)
    assert [(code, element) for code, element, message in found if "too" in message] == [
        ("duplicate-value", "pages.lesson_copy")
    ]


def test_no_page_has_the_path_of_a_shared_page() -> None:
    text = definition_text().replace(
        "  course:\n    path:",
        '  guest:\n    path: "/shared/lessons/{token}"\n    title: Guest\n  course:\n    path:',
    )
    found = diagnostics(text)
    assert "duplicate-value" in [code for code, _, _ in found]


def test_the_fastapi_app_has_the_share_endpoints_and_the_table() -> None:
    files = files_of(definition_text(), fastapi.BINDING)
    share = files["app/features/lessons/share.py"]
    assert '"/lessons/{id}/share"' in share
    assert '"/shared/lessons/{token}"' in share
    assert 'operation_id="create_lesson_share_link"' in share
    assert 'RelatedStep("course", Course' in share
    assert "app/core/sharing.py" in files
    assert "tests/features/lessons/test_share.py" in files
    migration = next(content for path, content in files.items() if path.endswith("0001_schema.py"))
    assert '"share_links"' in migration
    assert "app/features/courses/share.py" not in files


def test_the_nextjs_app_has_the_shared_page_and_the_actions() -> None:
    files = files_of(definition_text(), nextjs.BINDING)
    page = files["app/(shared-links)/shared/lessons/[token]/page.tsx"]
    assert "notFound()" in page
    assert "index: false" in page
    assert "app/(shared-links)/layout.tsx" in files
    assert "src/shared/db/schema/share-links.ts" in files
    actions = files["src/entities/lesson/api/lesson-actions.ts"]
    for action in (
        "getLessonShareLinkAction",
        "createLessonShareLinkAction",
        "revokeLessonShareLinkAction",
    ):
        assert f"export async function {action}" in actions
    assert "lessonSharing" in files["src/entities/lesson/index.ts"]
    assert "<ShareButton" in files["src/pages/lesson/ui/lesson-page.tsx"]
    assert "<ShareButton" not in files["src/pages/course/ui/course-page.tsx"]
    assert "src/widgets/lesson-detail/ui/lesson-detail-shared-view.tsx" in files
    assert "src/widgets/course-detail/ui/course-detail-shared-view.tsx" not in files
    assert "src/shared/ui/dialog.tsx" in files


def test_the_react_app_with_mock_data_keeps_the_links_in_the_browser() -> None:
    files = files_of(definition_text(), react.BINDING)
    router = files["src/app/router.tsx"]
    assert '{ path: "/shared/lessons/:token", element: <LessonDetailSharedView /> }' in router
    assert "<SharedLayout />" in router
    api = files["src/entities/lesson/api/lesson-api.ts"]
    assert 'lessonApi.sharing(() => requireOperation("update_lesson"))' in api
    assert "export function readLessonShared(token: string)" in api
    assert "localStorage" in files["src/shared/api/mock-store.ts"]
    view = files["src/widgets/lesson-detail/ui/lesson-detail-shared-view.tsx"]
    assert "courseApi.list()" in view
    assert "<ShareButton" in files["src/pages/lesson/ui/lesson-page.tsx"]


def test_the_react_app_with_the_api_reads_the_related_records_of_the_link() -> None:
    text = definition_text().replace(
        "app: { name: school, title: School }",
        "app: { name: school, title: School, x-react-data: api }",
    )
    files = files_of(text, react.BINDING)
    assert "lessonApi.sharing();" in files["src/entities/lesson/api/lesson-api.ts"]
    store = files["src/shared/api/http-store.ts"]
    assert '"/share"' in store
    assert "`/shared${this.path}/" in store
    view = files["src/widgets/lesson-detail/ui/lesson-detail-shared-view.tsx"]
    assert "courseApi.fromJson(item)" in view
    assert "courseApi.list()" not in view


@pytest.mark.parametrize("binding", [fastapi.BINDING, nextjs.BINDING, react.BINDING])
def test_an_app_without_share_has_no_share_files(binding: Binding) -> None:
    files = files_of(definition_text().replace("    share: true\n", ""), binding)
    assert not [path for path in files if re.search(r"share[-_.]|sharing|shared-", path)]
    assert not [content for content in files.values() if "ShareButton" in content]


def test_the_course_hub_shares_its_lessons() -> None:
    definition = load_definition(FIXTURE)
    assert validate_definition(definition) == []
    assert definition.pages["lesson_detail"].share is True
