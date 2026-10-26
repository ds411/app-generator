"""The notices of the changes of records: the DSL, the checks, and the FastAPI app (ADR 0041)."""

from textwrap import dedent, indent

import pytest

from appgen.bindings import fastapi
from appgen.dsl import load_definition_text, validate_definition
from appgen.dsl.notifications import Notification
from appgen.gen.elements import element_kind
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Person:
        crud: true
        display_field: name
        fields:
          name: { type: string, required: true }
          email: { type: email, required: true, unique: true }
        relations:
          teams: { kind: many_to_many, target: Team, inverse: members }
      Team:
        crud: true
        display_field: name
        fields:
          name: { type: string, required: true }
        relations:
          members: { kind: many_to_many, target: Person, inverse: teams }
      Project:
        crud: true
        display_field: name
        fields:
          name: { type: string, required: true }
        relations:
          team: { kind: many_to_one, target: Team, required: true }
      Task:
        crud: true
        display_field: title
        fields:
          title: { type: string, required: true }
          status: { type: enum, values: [open, done], default: open }
          points: { type: integer }
          score: { type: integer, computed: points * 2 }
          scan: { type: file }
        relations:
          project: { kind: many_to_one, target: Project, required: true }
          assignee: { kind: many_to_one, target: Person }
          comments: { kind: one_to_many, target: Comment, inverse: task }
      Comment:
        crud: true
        fields:
          body: { type: text, required: true }
        relations:
          task: { kind: many_to_one, target: Task, required: true }
    storage: { kind: local }
    workflows:
      task_status:
        entity: Task
        field: status
        transitions:
          close: { from: [open], to: done }
    auth:
      user_entity: Person
      username_field: email
    notifications:
      task_assigned:
        entity: Task
        event: changed
        fields: [assignee]
        receivers: [assignee]
        text: The task {title} of {project} is yours.
      task_added:
        entity: Task
        event: created
        receivers: [project.team.members]
        text: The task {title} is new.
      task_closed:
        entity: Task
        transition: close
        receivers: [assignee, project.team.members]
        text: The task {title} is done.
    """
)


def with_notification(text: str) -> str:
    """Return the base definition with one more notification `other`."""
    return BASE + "  other:\n" + indent(dedent(text), "    ")


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def messages(text: str) -> list[str]:
    definition = load_definition_text(text, "app.yaml")
    return [d.message for d in validate_definition(definition)]


def files_of(text: str) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_a_notification_is_an_element_with_its_own_kind() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert codes(BASE) == []
    notification = definition.notifications["task_closed"]
    assert isinstance(notification, Notification)
    assert notification.id == "notifications.task_closed"
    assert element_kind(("notifications", "task_closed"), notification) == "notification"
    assert notification.receivers == ["assignee", "project.team.members"]
    assert notification.transition_parts() == (None, "close")
    assert definition.notifications["task_assigned"].values() == ["title", "project"]


def test_a_notification_needs_auth() -> None:
    text = BASE.replace("auth:\n  user_entity: Person\n  username_field: email\n", "")
    assert codes(text) == [
        ("missing-key", "notifications.task_assigned"),
        ("missing-key", "notifications.task_added"),
        ("missing-key", "notifications.task_closed"),
    ]


def test_a_notification_has_an_event_or_a_transition() -> None:
    neither = with_notification(
        """\
        entity: Task
        receivers: [assignee]
        text: Hello.
        """
    )
    both = with_notification(
        """\
        entity: Task
        event: created
        transition: close
        receivers: [assignee]
        text: Hello.
        """
    )
    assert codes(neither) == [("missing-key", "notifications.other")]
    assert codes(both) == [("invalid-option", "notifications.other")]


def test_fields_are_only_for_changed_and_name_stored_fields_or_many_to_one_relations() -> None:
    created = with_notification(
        """\
        entity: Task
        event: created
        fields: [title]
        receivers: [assignee]
        text: Hello.
        """
    )
    unsuitable = with_notification(
        """\
        entity: Task
        event: changed
        fields: [score, scan, comments, nothing]
        receivers: [assignee]
        text: Hello.
        """
    )
    assert codes(created) == [("invalid-option", "notifications.other")]
    assert messages(unsuitable) == [
        "The field or relation 'score' is the computed field 'Task.score'. A notification "
        "uses the stored fields, except the files, and the 'many_to_one' relations.",
        "The field or relation 'scan' is the file field 'Task.scan'. A notification uses the "
        "stored fields, except the files, and the 'many_to_one' relations.",
        "The field or relation 'comments' is the 'one_to_many' relation 'Task.comments'. A "
        "notification uses the stored fields, except the files, and the 'many_to_one' "
        "relations.",
        "The field or relation 'nothing' does not exist.",
    ]


def test_a_transition_is_a_transition_of_a_workflow_of_the_entity() -> None:
    unknown = with_notification(
        """\
        entity: Task
        transition: clos
        receivers: [assignee]
        text: Hello.
        """
    )
    named = with_notification(
        """\
        entity: Task
        transition: task_status.close
        receivers: [assignee]
        text: Hello.
        """
    )
    other_workflow = with_notification(
        """\
        entity: Task
        transition: status.close
        receivers: [assignee]
        text: Hello.
        """
    )
    assert codes(named) == []
    assert codes(unknown) == [("unknown-reference", "notifications.other")]
    definition = load_definition_text(unknown, "app.yaml")
    [diagnostic] = validate_definition(definition)
    assert diagnostic.hint == "Did you mean 'close'?"
    assert messages(other_workflow) == ["The entity 'Task' has no workflow 'status'."]


def test_two_workflows_with_the_transition_need_the_name_of_the_workflow() -> None:
    text = BASE.replace(
        "    transitions:\n      close: { from: [open], to: done }\n",
        "    transitions:\n      close: { from: [open], to: done }\n"
        "  task_review:\n    entity: Task\n    field: review\n"
        "    transitions:\n      close: { from: [new], to: closed }\n",
    ).replace(
        "      status: { type: enum, values: [open, done], default: open }\n",
        "      status: { type: enum, values: [open, done], default: open }\n"
        "      review: { type: enum, values: [new, closed], default: new }\n",
    )
    [diagnostic] = validate_definition(load_definition_text(text, "app.yaml"))
    assert diagnostic.code == "invalid-value"
    assert diagnostic.hint == "Name the workflow, for example 'task_status.close'."
    named = text.replace("    transition: close\n", "    transition: task_review.close\n")
    assert codes(named) == []


def test_a_receiver_path_ends_at_the_user_entity() -> None:
    text = with_notification(
        """\
        entity: Task
        event: created
        receivers: [project, project.team, title, comments, nothing, assignee, assignee]
        text: Hello.
        """
    )
    assert messages(text) == [
        "The paths in 'receivers' must be unique.",
        "The receiver 'project' must end with a relation to the user entity 'Person'.",
        "The receiver 'project.team' must end with a relation to the user entity 'Person'.",
        "The step 'title' of the receiver is a field of 'Task', not a relation.",
        "Each step of the receiver must be a many-to-one or a many-to-many relation, and "
        "'Task.comments' is a 'one_to_many' relation.",
        "The relation 'nothing' of 'Task' does not exist.",
    ]


def test_a_value_in_braces_is_a_stored_field_or_a_many_to_one_relation() -> None:
    text = with_notification(
        """\
        entity: Task
        event: created
        receivers: [assignee]
        text: "{title} {score} {comments} {nothing}"
        """
    )
    assert [m.split(" is ")[0].split(" does ")[0] for m in messages(text)] == [
        "The value in braces 'score'",
        "The value in braces 'comments'",
        "The value in braces 'nothing'",
    ]


def test_the_repository_adds_the_notices_after_the_change() -> None:
    files = files_of(BASE)
    repository = files["app/features/tasks/repository.py"]
    assert 'TASK_ASSIGNED_FIELDS = ["assignee_id"]\n' in repository
    assert "    await notify(session, record, None)\n" in repository
    assert "    await notify(session, record, before)\n" in repository
    assert '    before = {"status": record.status, "assignee_id": record.assignee_id}\n' in (
        repository
    )
    assert "    if changed(record, before, TASK_ASSIGNED_FIELDS):\n" in repository
    assert '    if record.status == "done" and before["status"] == "open":\n' in repository
    assert (
        '            *await path_users(session, Task, record.id, ("project", "team", "members")),\n'
    ) in repository
    assert (
        '            "project": await record_text(session, Project.name, Project.id, '
        "record.project_id),\n"
    ) in repository
    assert '        add_notices(session, "task_added", "Task", record.id, users, values)\n' in (
        repository
    )
    assert "notify" not in files["app/features/persons/repository.py"]


def test_the_fastapi_app_has_the_table_the_endpoints_and_the_tests_of_the_notices() -> None:
    files = files_of(BASE)
    notifications = files["app/core/notifications.py"]
    assert '    __tablename__ = "notices"\n' in notifications
    assert '    "task_assigned": "The task {title} of {project} is yours.",\n' in notifications
    assert "from app.core.auth" not in notifications
    notices = files["app/core/notices.py"]
    assert 'router = APIRouter(prefix="/notices", tags=["notices"])\n' in notices
    assert '    operation_id="list_notices",\n' in notices
    assert '    "/{id}/read",\n' in notices
    assert '    "/read",\n' in notices
    assert "from app.core.notices import router as notices_router\n" in files["app/main.py"]
    assert "from app.core.notifications import Notice\n" in files["app/models.py"]
    migration = files["migrations/versions/0001_schema.py"]
    assert '        "notices",\n' in migration
    assert '            name="fk_notices_user_id_persons",\n' in migration
    assert '    op.drop_table("notices")\n' in migration
    assert "    session.info[USER_KEY] = user.id\n" in files["app/core/auth.py"]
    tests = files["tests/features/tasks/test_notifications.py"]
    assert "async def test_task_added_gives_each_receiver_a_notice(" in tests
    assert "async def test_task_closed_gives_no_notice_to_the_user_of_the_change(" in tests
    assert "    team = await make_team(session, member_ids=[user_id])\n" in tests
    assert "tests/test_notices.py" in files
    assert "## Notices" in files["README.md"]


def test_the_text_of_a_notice_has_the_language_of_the_request() -> None:
    text = BASE + dedent(
        """\
        translations:
          default: en
          languages:
            en: { label: English }
            de:
              label: Deutsch
              text:
                "The task {title} of {project} is yours.":
                  "Die Aufgabe {title} von {project} gehört dir."
        """
    )
    files = files_of(text)
    notifications = files["app/core/notifications.py"]
    assert "    text = t(TEXTS.get(notice.notification, notice.notification))\n" in notifications
    assert "    return _VALUE.sub(lambda m: values.get(m[1], m[0]), text)\n" in notifications
    tests = files["tests/test_notices.py"]
    assert 'LANGUAGE = "de"\n' in tests
    assert 'TRANSLATION = "Die Aufgabe <title> von <project> gehört dir."\n' in tests
    assert "async def test_the_text_has_the_language_of_the_request(" in tests
    assert "LANGUAGE" not in files_of(BASE)["tests/test_notices.py"]


def test_the_fastapi_app_without_notifications_has_no_notices() -> None:
    files = files_of(BASE[: BASE.index("notifications:")])
    assert "app/core/notifications.py" not in files
    assert "app/core/notices.py" not in files
    assert "notify(" not in files["app/features/tasks/repository.py"]
    assert "USER_KEY" not in files["app/core/auth.py"]


def test_an_entity_with_the_table_of_the_notices_is_an_error() -> None:
    text = BASE.replace("  Comment:\n", "  Comment:\n    x-fastapi-table: notices\n")
    definition = load_definition_text(text, "app.yaml")
    with pytest.raises(GenerationError, match="the table 'notices' of the notices"):
        generate(definition, fastapi.BINDING)
