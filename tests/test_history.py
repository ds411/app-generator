"""The change log of the records: the DSL, the checks, and the FastAPI app (ADR 0040)."""

from pathlib import Path
from textwrap import dedent

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.history import History
from appgen.dsl.schema import json_schema
from appgen.gen.elements import element_kind
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "room-booking" / "app.yaml"
TOTALS = ROOT / "tests" / "fixtures" / "totals.yaml"
INVOICES = ROOT / "tests" / "fixtures" / "invoices.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    storage: { kind: local }
    entities:
      Task:
        crud: true
        history: true
        fields:
          title: { type: string, required: true }
          points: { type: integer, min: 0, max: 100 }
          score: { type: integer, computed: points * 2 }
          status: { type: enum, values: [open, done], default: open }
          scan: { type: file }
        relations:
          project: { kind: many_to_one, target: Project }
      Project:
        crud: true
        fields:
          name: { type: string, required: true }
        relations:
          tasks: { kind: one_to_many, target: Task, inverse: project }
    """
)


def with_history(text: str) -> str:
    """Return the base definition with another `history` of Task."""
    return BASE.replace("    history: true\n", f"    history: {text}\n", 1)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_history_is_true_or_a_mapping_with_fields() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    task = definition.entities["Task"]
    assert task.history is not None
    assert task.history.fields is None
    # The log keeps the stored fields without the files, and the many_to_one relations.
    assert task.history_members == ["title", "points", "status", "project"]
    assert definition.entities["Project"].history_members == []
    assert isinstance(definition.find("entities.Task.history"), History)
    path = ("entities", "Task", "history")
    assert element_kind(path, definition.elements["entities.Task.history"]) == "history"
    assert validate_definition(definition) == []

    text = with_history("{ fields: [status, project], description: The audit log. }")
    task = load_definition_text(text, "app.yaml").entities["Task"]
    assert task.history_members == ["status", "project"]
    assert load_definition_text(with_history("false"), "app.yaml").entities["Task"].history is None


def test_the_schema_has_the_short_form_of_history() -> None:
    schema = json_schema()
    assert schema["$defs"]["Entity"]["properties"]["history"]["$ref"] == "#/$defs/HistoryInput"
    assert schema["$defs"]["HistoryInput"]["anyOf"] == [
        {"type": "boolean"},
        {"$ref": "#/$defs/History"},
        {"type": "null"},
    ]
    assert set(schema["$defs"]["History"]["properties"]) == {"fields", "description"}


def test_the_fields_of_history_are_stored_fields_and_many_to_one_relations() -> None:
    assert codes(with_history("{ fields: [title, titel, score, scan, title] }")) == [
        ("duplicate-name", "entities.Task.history"),
        ("unknown-reference", "entities.Task.history"),
        ("unsuitable-field", "entities.Task.history"),
        ("unsuitable-field", "entities.Task.history"),
    ]
    text = BASE.replace(
        "      name: { type: string, required: true }\n",
        "      name: { type: string, required: true }\n    history: { fields: [tasks] }\n",
    )
    assert codes(text) == [("unsuitable-field", "entities.Project.history")]


def test_the_fastapi_repository_adds_the_entries_in_the_transaction_of_the_change() -> None:
    files = files_of(BASE)
    repository = files["app/features/tasks/repository.py"]
    assert (
        'HISTORY = {"title": "title", "points": "points", "status": "status", '
        '"project": "project_id"}\n'
    ) in repository
    assert (
        '    add_entry(session, "Task", record.id, "created", None, snapshot(record, HISTORY))\n'
    ) in repository
    assert '    action: Action = "changed",\n' in repository
    assert "    kept = snapshot(record, HISTORY)\n" in repository
    assert (
        '    add_entry(session, "Task", record.id, action, kept, snapshot(record, HISTORY))\n'
    ) in repository
    assert '    add_entry(session, "Task", record.id, "deleted", kept, None)\n' in repository
    assert (
        "async def restore(session: AsyncSession, record: Task, entry: HistoryEntry) -> Task:\n"
    ) in repository
    assert '    return await update(session, record, data, action="restored")\n' in repository
    assert "add_entry" not in files["app/features/projects/repository.py"]
    history = files["app/core/history.py"]
    assert '    __tablename__ = "history_entries"\n' in history
    assert "class HistoryEntryRead(ReadModel):" in history
    assert "from app.core.history import HistoryEntry\n" in files["app/models.py"]
    migration = files["migrations/versions/0001_schema.py"]
    assert '        "history_entries",\n' in migration
    assert (
        '    op.create_index("ix_history_entries_record_id", "history_entries", ["record_id"])\n'
    ) in migration
    assert '    op.drop_table("history_entries")\n' in migration


def test_the_lines_of_a_record_add_entries_too() -> None:
    definition = load_definition(TOTALS)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    repository = files["app/features/invoice_lines/repository.py"]
    change = repository.split("async def change(", 1)[1].split("\n\n\n", 1)[0]
    assert '    action: Action = "changed",\n' in change
    assert change.endswith(
        '    add_entry(session, "InvoiceLine", record.id, action, kept, snapshot(record, HISTORY))'
    )
    assert "    await change(session, record, data, action=action)\n" in repository
    remove = repository.split("async def remove(", 1)[1].split("\n\n\n", 1)[0]
    assert remove.endswith(
        '    add_entry(session, "InvoiceLine", record.id, "deleted", kept, None)'
    )


def test_the_entry_of_a_create_has_the_number_of_a_sequence() -> None:
    definition = load_definition(INVOICES)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    repository = files["app/features/invoices/repository.py"]
    assert (
        "    session.add(record)\n"
        "    # The database gives the numbers of the sequences, for the entry of the change log.\n"
        "    await flush(session)\n"
    ) in repository
    # The inputs do not have the number, so a restore keeps it, and the tests change another field.
    assert '    values.pop("number", None)\n' in repository
    tests = files["tests/features/invoices/test_history.py"]
    assert "    old = record.issued_on\n" in tests


def test_the_fastapi_app_has_the_endpoints_and_the_tests_of_the_change_log() -> None:
    files = files_of(BASE)
    endpoints = files["app/features/tasks/history.py"]
    assert '    "/{id}/history",\n' in endpoints
    assert '    operation_id="list_task_history",\n' in endpoints
    assert '    "/{id}/history/{entry_id}/restore",\n' in endpoints
    assert '    operation_id="restore_task_history_entry",\n' in endpoints
    assert "router.include_router(history.router)\n" in files["app/features/tasks/router.py"]
    tests = files["tests/features/tasks/test_history.py"]
    names = [
        line.split("(")[0][10:] for line in tests.splitlines() if line.startswith("async def test_")
    ]
    assert names == [
        "test_a_create_adds_an_entry_with_the_new_values",
        "test_a_change_adds_an_entry_with_the_old_and_the_new_value",
        "test_a_change_without_a_new_value_adds_no_entry",
        "test_a_delete_adds_an_entry_with_the_old_values",
        "test_the_endpoint_gives_the_entries_of_a_record_the_newest_first",
        "test_the_endpoint_gives_404_for_a_missing_record",
        "test_a_restore_gives_the_old_value_back",
        "test_a_restore_of_the_entry_of_a_create_gives_422",
        "test_a_restore_of_an_entry_of_another_record_gives_404",
    ]
    assert "## Change log" in files["README.md"]


def test_the_endpoints_of_the_change_log_need_the_operations_of_the_entity() -> None:
    files = files_of(BASE.replace("    crud: true\n", "    crud: [create, list, update]\n", 1))
    endpoints = files["app/features/tasks/history.py"]
    assert '    "/{id}/history",\n' not in endpoints
    assert '    "/{id}/history/{entry_id}/restore",\n' in endpoints
    files = files_of(BASE.replace("    crud: true\n", "    crud: [create, list]\n", 1))
    assert "app/features/tasks/history.py" not in files
    assert "history.router" not in files["app/features/tasks/router.py"]
    assert "add_entry(" in files["app/features/tasks/repository.py"]
    assert "tests/features/tasks/test_history.py" in files


def test_the_fastapi_app_without_history_keeps_no_change_log() -> None:
    files = files_of(BASE.replace("    history: true\n", "", 1))
    assert "app/core/history.py" not in files
    assert "add_entry" not in files["app/features/tasks/repository.py"]
    assert "history_entries" not in files["migrations/versions/0001_schema.py"]
    assert not [path for path in files if path.endswith("history.py")]
    assert "## Change log" not in files["README.md"]


def test_the_room_booking_example_keeps_the_user_and_checks_the_permissions() -> None:
    definition = load_definition(EXAMPLE)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    assert 'USER_KEY = "appgen.user"\n' in files["app/core/db.py"]
    auth = files["app/core/auth.py"]
    assert "from app.core.db import USER_KEY, " in auth
    assert "    session.info[USER_KEY] = user.id\n    return user\n" in auth
    history = files["app/core/history.py"]
    assert "session.info.get(USER_KEY)" in history
    access = files["app/core/access.py"]
    assert '    "list_booking_history": "read_booking",\n' in access
    assert '    "restore_booking_history_entry": "update_booking",\n' in access
    tests = files["tests/features/bookings/test_history.py"]
    assert "async def test_an_entry_has_the_signed_in_user(" in tests


def test_the_front_ends_keep_the_change_log_later() -> None:
    assert "history" in fastapi.BINDING.covers
    for binding in (nextjs, react):
        assert "history" in binding.BINDING.excludes
