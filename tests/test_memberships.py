"""The roles of the users in the records of a scope (ADR 0048): the DSL, the checks, and the app."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.access import scope_entities
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "courses.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: school, title: School }
    entities:
      User:
        crud: {}
        fields:
          email: { type: email, required: true, unique: true }
          role: { type: enum, values: [admin, member], default: member }
        relations:
          enrollments: { kind: one_to_many, target: Enrollment, inverse: user }
      Course:
        crud: {}
        fields:
          title: { type: string, required: true }
        relations:
          lessons: { kind: one_to_many, target: Lesson, inverse: course }
          enrollments: { kind: one_to_many, target: Enrollment, inverse: course }
      Lesson:
        crud: {}
        fields:
          title: { type: string, required: true }
        relations:
          course: { kind: many_to_one, target: Course, required: true, inverse: lessons }
          notes: { kind: one_to_many, target: Note, inverse: lesson }
      Note:
        crud: {}
        fields:
          text: { type: text, required: true }
        relations:
          lesson: { kind: many_to_one, target: Lesson, required: true, inverse: notes }
      Enrollment:
        crud: {}
        fields:
          role: { type: enum, values: [teacher, student], default: student }
        relations:
          user: { kind: many_to_one, target: User, required: true, inverse: enrollments }
          course: { kind: many_to_one, target: Course, required: true, inverse: enrollments }
    auth:
      user_entity: User
      username_field: email
    access:
      role_field: role
      roles:
        admin: { operations: ["*"], pages: ["*"] }
        member: { operations: [list_courses, read_course], pages: ["*"] }
      memberships:
        entity: Enrollment
        user: user
        scope: course
        role_field: role
        roles:
          teacher:
            operations: [update_course, create_lesson, update_lesson, list_notes, read_note]
          student:
            operations: [list_lessons, read_lesson]
        paths:
          Lesson: course
          Note: lesson.course
    """
)


def diagnostics(text: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def codes(text: str) -> list[str]:
    return [code for code, _, _ in diagnostics(text)]


def files_of(text: str) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_the_memberships_are_valid() -> None:
    assert diagnostics(BASE) == []


def test_the_entities_of_the_scope_are_the_scope_entity_and_the_paths() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert scope_entities(definition) == {"Course": "", "Lesson": "course", "Note": "lesson.course"}


def test_the_membership_entity_exists() -> None:
    text = BASE.replace("entity: Enrollment\n", "entity: Enrolment\n")
    assert diagnostics(text) == [
        (
            "unknown-reference",
            "access.memberships",
            "The entity 'Enrolment' does not exist.",
        )
    ]


def test_the_user_and_the_scope_are_many_to_one_relations() -> None:
    text = BASE.replace("user: user\n", "user: users\n")
    assert codes(text) == ["unknown-reference"]
    text = BASE.replace("scope: course\n", "scope: user\n")
    assert next(m for _, _, m in diagnostics(text)) == (
        "'scope' must be a relation to another entity than the user entity, for example a team "
        "or a course."
    )
    text = BASE.replace("user: user\n", "user: course\n")
    assert next(m for _, _, m in diagnostics(text)) == (
        "'user' must be a relation to the user entity 'User'."
    )


def test_the_role_field_is_an_enum_field_with_the_roles() -> None:
    text = BASE.replace(
        "role: { type: enum, values: [teacher, student], default: student }",
        "role: { type: string }",
    )
    assert diagnostics(text) == [
        (
            "unsuitable-field",
            "access.memberships",
            "The role field of the memberships must be an enum field of 'Enrollment'.",
        )
    ]
    text = BASE.replace("values: [teacher, student]", "values: [teacher, pupil]").replace(
        "default: student", "default: pupil"
    )
    assert diagnostics(text) == [
        (
            "unknown-reference",
            "access.memberships.roles.student",
            "The role value 'student' does not exist.",
        )
    ]


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("lesson.title", "The relation of 'Lesson' 'title' does not exist."),
        (
            "lesson",
            "The path 'lesson' of 'Note' must end with a relation to the scope entity 'Course'.",
        ),
        (
            "lesson.course.lessons",
            "Each step of the path of 'Note' must be a many-to-one relation, and "
            "'Course.lessons' is a 'one_to_many' relation.",
        ),
    ],
)
def test_a_path_goes_by_many_to_one_relations_to_the_scope(path: str, message: str) -> None:
    text = BASE.replace("Note: lesson.course\n", f"Note: {path}\n")
    assert [m for _, _, m in diagnostics(text)] == [message]


def test_the_scope_entity_has_no_path() -> None:
    text = BASE.replace("Lesson: course\n", "Lesson: course\n      Course: lessons\n")
    assert codes(text) == ["invalid-value"]


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ("delete_lesn", "The operation 'delete_lesn' does not exist."),
        (
            "read_user",
            "The operation 'read_user' is an operation of 'User', which is not an entity of the "
            "scope 'Course'.",
        ),
    ],
)
def test_a_role_names_operations_of_the_entities_of_the_scope(operation: str, message: str) -> None:
    text = BASE.replace("[list_lessons, read_lesson]", f"[list_lessons, {operation}]")
    assert [m for _, _, m in diagnostics(text)] == [message]


def test_the_fastapi_app_gives_the_operations_of_the_roles_in_their_scopes() -> None:
    files = files_of(BASE)
    access = files["app/core/access.py"]
    assert "MEMBER_ROLES: dict[str, frozenset[str]] = {" in access
    assert '"student": frozenset(\n        {\n            "list_lessons",' in access
    assert 'SCOPE_ENTITIES = frozenset({"Course", "Lesson", "Note"})' in access
    assert "async def member_scopes(" in access
    notes = files["app/features/notes/repository.py"]
    assert "def in_scopes(scopes: Collection[UUID]) -> ColumnElement[bool]:" in notes
    assert "Note.lesson.has(Lesson.course_id.in_(scopes))" in notes
    assert "Course.id.in_(scopes)" in files["app/features/courses/repository.py"]
    assert "in_scopes" not in files["app/features/users/repository.py"]
    tests = files["tests/test_memberships.py"]
    for name in ("update_course", "update_lesson", "read_note"):
        assert f"async def test_a_role_of_a_membership_gives_{name}_in_its_scope(" in tests


def test_an_app_without_memberships_has_no_member_code() -> None:
    text = BASE[: BASE.index("  memberships:")]
    files = files_of(text)
    assert "tests/test_memberships.py" not in files
    assert "MEMBER_ROLES" not in files["app/core/access.py"]
    assert not [path for path, content in files.items() if "in_scopes" in content]


def test_the_course_hub_has_teachers_and_students() -> None:
    definition = load_definition(FIXTURE)
    assert validate_definition(definition) == []
    assert definition.access is not None and definition.access.memberships is not None
    assert set(definition.access.memberships.roles) == {"teacher", "student"}
