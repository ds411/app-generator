"""The mentions of users in a text: the DSL, the checks, and the apps (ADR 0043)."""

import re
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.bindings.shared.notices import MENTION, MENTION_PATTERN, MENTION_TEXT
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate

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
      Task:
        crud: true
        display_field: title
        fields:
          title: { type: string, required: true }
          note: { type: text, mentions: true }
    auth:
      user_entity: Person
      username_field: email
    ui:
      views:
        person_detail: { kind: detail, entity: Person }
        task_table:
          kind: table
          entity: Task
          columns: { title: {}, note: {} }
      forms:
        new_task:
          entity: Task
          operation: create_task
          fields: { title: {}, note: { widget: textarea, rows: 3 } }
    pages:
      tasks: { path: /tasks, title: Tasks, content: { view: task_table } }
      new_task: { path: /tasks/new, title: New task, content: { form: new_task } }
      person: { path: "/people/{id}", title: Person, content: { view: person_detail } }
    """
)
API = BASE.replace("title: Tracker }", "title: Tracker, x-react-data: api }")
NOTE = "entities.Task.fields.note"


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_text_with_mentions_is_valid() -> None:
    assert codes(BASE) == []


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("note: { type: string, mentions: true }", "invalid-option"),
        ("note: { type: text, mentions: true, computed: title }", "invalid-option"),
    ],
)
def test_mentions_are_only_for_a_stored_text(change: str, code: str) -> None:
    text = BASE.replace("note: { type: text, mentions: true }", change)
    assert (code, NOTE) in codes(text)


def test_mentions_need_auth() -> None:
    text = BASE.split("auth:")[0] + "ui:" + BASE.split("ui:")[1]
    assert ("invalid-option", NOTE) in codes(text)


def test_the_pattern_of_a_mention_finds_the_name_and_the_id() -> None:
    text = "Ask @[Ann Lee](0b7f9c1e-1234-4abc-8def-0123456789ab), not @[x](12) or @ann."
    assert re.findall(MENTION_PATTERN, text) == [
        ("Ann Lee", "0b7f9c1e-1234-4abc-8def-0123456789ab")
    ]


def test_the_fastapi_app_adds_a_notice_for_each_new_mention() -> None:
    files = files_of(BASE, fastapi.BINDING)
    repository = files["app/features/tasks/repository.py"]
    assert "await mention(session, record, None)" in repository
    assert "await mention(session, record, before)" in repository
    assert '"note": record.note' in repository
    assert "Person.id," in repository
    core = files["app/core/notifications.py"]
    assert f'MENTION = "{MENTION}"' in core
    assert f'MENTION: "{MENTION_TEXT}",' in core
    assert "async def add_mentions(" in core
    # The app has no notification, so the notices are for the mentions only.
    assert "class Notice(Base):" in core
    assert "app.include_router(notices_router)" in files["app/main.py"]
    assert '"notices",' in files["migrations/versions/0001_schema.py"]
    test = files["tests/features/tasks/test_mentions.py"]
    assert "async def test_a_new_mention_in_note_gives_the_user_a_notice(" in test
    assert 'NAME = "@mention"' in files["tests/test_notices.py"]


def test_the_next_js_app_adds_the_notices_in_the_repository() -> None:
    files = files_of(BASE, nextjs.BINDING)
    repository = files["src/entities/task/api/task-repository.ts"]
    assert (
        'await addMentions(tx, "Task", id, textValue(row.title), row.note, before?.note);'
        in repository
    )
    assert "export async function addMentions(" in files["src/shared/db/notices.ts"]
    assert "export function mentionParts(" in files["src/shared/lib/mentions.ts"]
    assert f'"{MENTION}": "{MENTION_TEXT}",' in files["src/features/notices/model/notice-texts.ts"]
    form = files["src/features/new-task-form/ui/new-task-form.tsx"]
    assert "<MentionTextarea" in form
    assert "options={[...related.person.values()]" in form
    view = files["src/widgets/task-table/ui/task-table-view.tsx"]
    assert "<MentionText text={row.note} />" in view
    text = files["src/shared/ui/values/mention-text.tsx"]
    assert 'href={pageHref("person", { id: part.id })}' in text


def test_the_react_app_adds_the_notices_in_the_mock_store_or_reads_the_api() -> None:
    files = files_of(BASE, react.BINDING)
    api = files["src/entities/task/api/task-api.ts"]
    call = 'addMentions("Task", record.id, textValue(record.title), record.note, before?.note, '
    assert call + '"Person");' in api
    assert "export function addMentions(" in files["src/shared/api/notices.ts"]
    remote = files_of(API, react.BINDING)
    form = remote["src/features/new-task-form/ui/new-task-form.tsx"]
    assert "source={personOptions}" in form
    assert "addMentions" not in remote["src/entities/task/api/task-api.ts"]
