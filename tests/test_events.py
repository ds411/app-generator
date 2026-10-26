"""The events of the entities: the DSL, the checks, and the data access of the apps (ADR 0031)."""

from pathlib import Path
from textwrap import dedent

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.diagnostics import DefinitionError
from appgen.dsl.events import Event
from appgen.dsl.schema import json_schema
from appgen.gen import Binding
from appgen.gen.elements import element_kind
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "room-booking" / "app.yaml"
RATES = ROOT / "examples" / "project-tracker" / "apis" / "exchange-rates.openapi.json"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Task:
        crud: true
        fields:
          title: { type: string, required: true }
          points: { type: integer, min: 0, max: 100 }
          score: { type: integer, computed: points * 2 }
          status: { type: enum, values: [open, done], default: open }
      Project:
        fields:
          name: { type: string, required: true }
    operations:
      notify:
        kind: custom
        entity: Task
        params:
          note: { type: string }
      recount: { kind: custom, entity: Task }
      escalate:
        kind: custom
        entity: Task
        params:
          level: { type: integer, required: true }
      archive_project: { kind: custom, entity: Project }
    workflows:
      task_flow:
        entity: Task
        field: status
        initial: open
        transitions:
          finish: { from: [open], to: done, run: notify }
          reopen: { from: [done], to: open }
    """
)


def task_events(text: str) -> str:
    """Return the base definition with the events of Task, from the lines of `events`."""
    lines = "".join(f"      {line}\n" for line in dedent(text).splitlines())
    return BASE.replace("    crud: true\n", "    crud: true\n    events:\n" + lines, 1)


EVENTS = task_events(
    """\
    created: notify
    changed: { operation: recount, fields: [points] }
    deleted: { operation: notify, description: Tell the team. }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_an_event_is_the_name_of_an_operation_or_a_mapping() -> None:
    definition = load_definition_text(EVENTS, "app.yaml")
    events = definition.entities["Task"].events
    assert {kind: (e.operation, e.fields) for kind, e in events.items()} == {
        "created": ("notify", None),
        "changed": ("recount", ["points"]),
        "deleted": ("notify", None),
    }
    assert isinstance(definition.find("entities.Task.events.created"), Event)
    path = ("entities", "Task", "events", "deleted")
    assert element_kind(path, definition.elements["entities.Task.events.deleted"]) == "event"
    assert definition.workflows["task_flow"].transitions["finish"].run == "notify"
    assert validate_definition(definition) == []


def test_an_event_has_one_of_three_names() -> None:
    try:
        load_definition_text(task_events("updated: notify"), "app.yaml")
    except DefinitionError as error:
        messages = [d.message for d in error.diagnostics]
    else:
        raise AssertionError("The definition loads.")
    assert messages == [
        "The value 'updated' is not valid. Expected 'created', 'changed' or 'deleted'."
    ]


def test_the_schema_has_the_short_form_of_an_event() -> None:
    schema = json_schema()
    assert schema["$defs"]["Entity"]["properties"]["events"]["propertyNames"] == {
        "$ref": "#/$defs/EventName"
    }
    assert schema["$defs"]["EventInput"]["anyOf"] == [
        {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        {"$ref": "#/$defs/Event"},
    ]
    assert "run" in schema["$defs"]["Transition"]["properties"]


def test_an_event_runs_a_custom_operation_of_its_entity_without_params() -> None:
    text = task_events(
        """\
        created: archive_project
        changed: escalate
        deleted: list_tasks
        """
    )
    assert codes(text) == [
        ("unsuitable-operation", "entities.Task.events.created"),
        ("unsuitable-operation", "entities.Task.events.changed"),
        ("unsuitable-operation", "entities.Task.events.deleted"),
    ]
    assert codes(task_events("created: notfy")) == [
        ("unknown-reference", "entities.Task.events.created")
    ]


def test_the_fields_of_an_event_are_stored_fields_of_changed() -> None:
    text = task_events(
        """\
        created: { operation: notify, fields: [title] }
        changed: { operation: recount, fields: [titel, score, points, points] }
        """
    )
    assert codes(text) == [
        ("invalid-option", "entities.Task.events.created"),
        ("duplicate-name", "entities.Task.events.changed"),
        ("unknown-reference", "entities.Task.events.changed"),
        ("unsuitable-field", "entities.Task.events.changed"),
    ]


def test_an_event_calls_no_api() -> None:
    text = EVENTS.replace(
        "  recount: { kind: custom, entity: Task }\n",
        "  recount: { kind: custom, entity: Task, apis: [crm] }\n",
    ) + (
        "apis:\n"
        "  crm:\n"
        f"    document: {RATES}\n"
        "    base_url_env: CRM_URL\n"
        "    operations: [getLatestRates]\n"
    )
    found = [
        d
        for d in validate_definition(load_definition_text(text, "app.yaml"))
        if d.element_id == "entities.Task.events.changed"
    ]
    assert [d.code for d in found] == ["unsuitable-operation"]
    assert "calls the API 'crm'" in found[0].message


def test_a_transition_runs_a_custom_operation_of_the_entity_of_its_workflow() -> None:
    text = BASE.replace("to: done, run: notify", "to: done, run: archive_project")
    text = text.replace("to: open }", "to: open, run: escalate }")
    assert codes(text) == [
        ("unsuitable-operation", "workflows.task_flow.transitions.finish"),
        ("unsuitable-operation", "workflows.task_flow.transitions.reopen"),
    ]


def test_the_fastapi_repository_runs_the_events_in_the_transaction_of_the_change() -> None:
    files = files_of(EVENTS)
    repository = files["app/features/tasks/repository.py"]
    add = repository.split("async def add(", 1)[1].split("\n\n\n", 1)[0]
    assert add.endswith(
        "    session.add(record)\n"
        "    # The operation of the event `created` finds the new record in the database.\n"
        "    await flush(session)\n"
        "    await on_created(session, record)\n"
        "    return record"
    )
    assert '    before = {"status": record.status, "points": record.points}\n' in repository
    assert "    await flush(session)\n    await on_changed(session, record, before)\n" in repository
    assert "    await flush(session)\n    await on_deleted(session, record)\n" in repository
    assert 'CHANGED_FIELDS = ["points"]\n' in repository
    assert (
        "    from app.features.tasks import notify_ext, recount_ext\n"
        "\n"
        "    # @trace workflows.task_flow.transitions.finish\n"
        '    if record.status == "done" and before["status"] == "open":\n'
        "        await run_event(session, notify_ext.notify, session, record, NotifyParams())\n"
        "    # @trace entities.Task.events.changed\n"
        "    if any(getattr(record, attr) != before[attr] for attr in CHANGED_FIELDS):\n"
        "        await run_event(session, recount_ext.recount, session, record)\n"
    ) in repository
    assert "    # @trace entities.Task.events.created\n" in repository
    assert "    # @trace entities.Task.events.deleted\n" in repository
    db = files["app/core/db.py"]
    assert (
        "    if session.info.get(EVENT_KEY):\n        await flush(session)\n        return\n" in db
    )
    assert "async def run_event[**P](" in db
    assert '("Task", task_repository, "on_changed"),' in files["tests/conftest.py"]
    assert '"events(*entities): ' in files["pyproject.toml"]


def test_the_fastapi_app_has_a_test_of_each_kind_of_event() -> None:
    tests = files_of(EVENTS)["tests/features/tasks/test_events.py"]
    names = [
        line.split("(")[0][10:] for line in tests.splitlines() if line.startswith("async def test_")
    ]
    assert names == [
        "test_created_runs_notify_after_the_record_is_stored",
        "test_created_stores_nothing_when_notify_fails",
        "test_changed_runs_recount_when_a_field_changes",
        "test_changed_keeps_the_record_when_recount_fails",
        "test_changed_does_not_run_recount_without_a_change",
        "test_changed_does_not_run_recount_for_other_fields",
        "test_finish_runs_notify",
        "test_finish_keeps_the_state_when_notify_fails",
        "test_deleted_runs_notify_after_the_record_is_deleted",
        "test_deleted_keeps_the_record_when_notify_fails",
        "test_a_change_in_the_operation_of_an_event_starts_no_event",
    ]
    assert 'pytestmark = [pytest.mark.anyio, pytest.mark.events("Task")]' in tests
    assert 'CHANGES = ["title", "points"]\n' in tests
    assert 'OTHERS = ["title"]\n' in tests


def test_a_transition_from_another_state_sets_the_state_in_the_test() -> None:
    text = BASE.replace("to: done, run: notify", "to: done").replace(
        "to: open }", "to: open, run: recount }"
    )
    tests = files_of(text)["tests/features/tasks/test_events.py"]
    assert '    record = await set_state(session, record, status="done")\n' in tests
    assert '    assert calls == [("recount", record.id, True)]\n' in tests


def test_the_fastapi_app_without_events_runs_none() -> None:
    files = files_of(BASE.replace(", run: notify", ""))
    assert "on_changed" not in files["app/features/tasks/repository.py"]
    assert "run_event" not in files["app/core/db.py"]
    assert "EVENTS" not in files["tests/conftest.py"]
    assert "events(*entities)" not in files["pyproject.toml"]
    assert not [path for path in files if path.endswith("test_events.py")]


def test_the_room_booking_example_tells_the_organizer_of_a_confirmation() -> None:
    definition = load_definition(EXAMPLE)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    repository = files["app/features/bookings/repository.py"]
    assert 'CHANGED_FIELDS = ["starts_at", "ends_at"]\n' in repository
    assert (
        '    if record.status == "confirmed" and before["status"] == "requested":\n'
        "        await run_event(session, notify_organizer_ext.notify_organizer, session, record)\n"
    ) in repository
    assert "tests/features/bookings/test_events.py" in files


def test_the_three_bindings_run_the_events() -> None:
    for binding in (fastapi, nextjs, react):
        assert "event" in binding.BINDING.covers
        assert "event" not in binding.BINDING.excludes


def ts_files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_the_nextjs_repository_runs_the_events_in_the_transaction_of_the_change() -> None:
    files = ts_files_of(EVENTS, nextjs.BINDING)
    repository = files["src/entities/task/api/task-repository.ts"]
    assert 'import { notifyParamsSchema } from "../model/schema";\n' in repository
    assert (
        "    created: async (record) => { // @trace entities.Task.events.created begin\n"
        '      const { notify } = await import("@/features/notify/api/notify.ext");\n'
        "      await notify(record, notifyParamsSchema.parse({}));\n"
        "    }, // @trace entities.Task.events.created end\n"
    ) in repository
    assert '      keys: ["points"],\n' in repository
    assert (
        '        field: "status",\n        from: ["open"],\n        to: "done",\n'
    ) in repository
    shared = files["src/shared/db/repository.ts"]
    assert 'import { type Database, getDb, runEvent } from "./client";' in shared
    assert "private changeEvents(before: Row | undefined, after: Row)" in shared
    assert "await this.runEvents(tx, record as T, [deleted]);" in shared
    client = files["src/shared/db/client.ts"]
    assert "const inEvent = new AsyncLocalStorage<true>();" in client
    assert "await inEvent.run(true, () => ambient.run(transaction, operation));" in client


def test_the_nextjs_repository_deletes_the_files_after_the_event_deleted() -> None:
    text = EVENTS.replace(
        "      status: { type: enum, values: [open, done], default: open }\n",
        "      status: { type: enum, values: [open, done], default: open }\n"
        "      scan: { type: file }\n",
    ).replace("entities:\n", "storage: { kind: local }\nentities:\n", 1)
    shared = ts_files_of(text, nextjs.BINDING)["src/shared/db/repository.ts"]
    # The operation gets the record in the transaction, and the files go after the commit.
    assert (
        "      const removed: Row[] = await getDb().transaction(async (tx) => {\n"
        "        const rows: Row[] = await tx.select().from(this.table)"
        ".where(eq(this.table.id, id)).limit(1);\n"
    ) in shared
    assert (
        "        await this.runEvents(tx, record as T, [deleted]);\n"
        "        return rows;\n"
        "      });\n"
        "      await deleteFiles(Object.keys(this.files)"
        ".map((key) => removed[0]?.[key] as StoredFile | null));\n"
        "      return;\n"
    ) in shared


def test_the_react_mock_store_runs_the_events_after_the_change() -> None:
    files = ts_files_of(EVENTS, react.BINDING)
    api = files["src/entities/task/api/task-api.ts"]
    assert ").withEvents({\n" in api
    assert "      await recount(record);\n" in api
    # The React app has no zod schema of the params without forms.
    assert "      await notify(record, {});\n" in api
    store = files["src/shared/api/mock-store.ts"]
    assert "  withEvents(events: Events<T>): this {" in store
    assert "let inEvent = false;" in store


def test_with_the_fastapi_app_the_react_app_runs_no_event() -> None:
    text = EVENTS.replace(
        "app: { name: tracker, title: Tracker }",
        "app:\n  name: tracker\n  title: Tracker\n  x-react-data: api",
    )
    files = ts_files_of(text, react.BINDING)
    api = files["src/entities/task/api/task-api.ts"]
    assert "// The FastAPI app runs the events of Task (ADR 0031).\n" in api
    assert "// @trace entities.Task.events.changed\n" in api
    assert "withEvents" not in api


def test_the_front_ends_without_events_run_none() -> None:
    text = BASE.replace(", run: notify", "")
    files = ts_files_of(text, nextjs.BINDING)
    assert "runEvent" not in files["src/shared/db/client.ts"]
    assert "events" not in files["src/entities/task/api/task-repository.ts"]
    assert "withEvents" not in ts_files_of(text, react.BINDING)["src/shared/api/mock-store.ts"]
