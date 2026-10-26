"""A change to the definition: the hand-written code stays, and the checker finds the drift.

The test generates each app of the project tracker, writes hand-written
code into an extension file, and then changes a copy of the definition:
it adds a field, renames an entity, and removes a page. After a new run,
the extension file keeps its code, and `appgen check` reports the traces
of the hand-written code to the renamed and the removed elements as
invalid, until the app developer updates them.
"""

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from appgen.cli import app
from appgen.dsl import AppDefinition, load_definition_text
from appgen.gen import find_binding, generate, read_manifest, write_result
from appgen.trace import check_traces, find_orphans, render_orphans

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

# An extension file of each app, and its comment prefix.
EXTENSION_FILES = {
    "nextjs": ("src/widgets/task-detail/ui/activity-tab.ext.tsx", "//"),
    "react": ("src/widgets/task-detail/ui/activity-tab.ext.tsx", "//"),
    "fastapi": ("app/features/tasks/complete_task_ext.py", "#"),
}

NEW_FIELD = "entities.Project.fields.priority"
RENAMED = ("entities.Comment", "entities.Remark")
REMOVED = "pages.people"


def change(text: str) -> str:
    """Add a field to Project, rename the entity Comment to Remark, and remove the page people."""
    project = (
        "    display_field: name\n    fields:\n"
        "      name: { type: string, required: true, max_length: 120 }\n      key:"
    )
    assert text.count(project) == 1
    text = text.replace(
        project,
        project.replace(
            "    fields:\n", "    fields:\n      priority: { type: integer, min: 1, max: 5 }\n"
        ),
    )
    text = re.sub(r"\bComment\b", "Remark", text)
    # The CRUD shorthand names the operations after the entity (ADR 0008).
    text = re.sub(r"\b(create|delete)_comment\b", r"\1_remark", text)
    for block in (
        "  people:\n    path: /people\n    title: People\n    entity: Person\n"
        "    content: { view: person_cards }\n",
        "        team:\n          label: Team\n          collapsible: true\n          items:\n"
        "            people: { page: people, icon: users }\n",
    ):
        assert text.count(block) == 1
        text = text.replace(block, "")
    return text


def hand_written(header: str, prefix: str) -> str:
    """Return the extension file with hand-written code that uses Comment and the page people."""
    lines = header.replace("@trace:gap", "@trace:manual").splitlines()[:2]
    return "\n".join(
        [
            *lines,
            f"{prefix} Hand-written code: the activity of a task, from its comments.",
            f"{prefix} @trace:manual {RENAMED[0]}",
            f"{prefix} @trace:manual {REMOVED}",
            f"{prefix} @trace:manual entities.Task",
            "",
        ]
    )


@pytest.fixture(scope="module")
def changed() -> AppDefinition:
    return load_definition_text(change(EXAMPLE.read_text()), str(EXAMPLE.parent / "changed.yaml"))


@pytest.mark.parametrize("binding_name", sorted(EXTENSION_FILES))
def test_extension_code_stays_and_the_check_reports_the_drift(
    tmp_path: Path, changed: AppDefinition, binding_name: str
) -> None:
    binding = find_binding(binding_name)
    original = load_definition_text(EXAMPLE.read_text(), str(EXAMPLE))
    write_result(generate(original, binding), tmp_path, binding_name)
    path, prefix = EXTENSION_FILES[binding_name]
    extension = tmp_path / path
    code = hand_written(extension.read_text(), prefix)
    extension.write_text(code)
    assert check_traces(original, tmp_path).invalid == []

    result = generate(changed, binding)
    write_result(result, tmp_path, binding_name)

    # The new run keeps the hand-written code.
    assert extension.read_text() == code
    report = check_traces(changed, tmp_path)
    # The generated code follows the definition: the new field and the
    # renamed entity have traces, and no generated trace is invalid.
    covered = {e.element_id for e in report.coverage.elements if e.status == "covered"}
    assert {NEW_FIELD, RENAMED[1]} <= covered
    assert not [t for t in report.traces if t.element_id == RENAMED[0]]
    # The hand-written code still refers to the old elements.
    # Other extension files of the renamed entity (for example its
    # validation in the FastAPI app) are drift too.
    invalid = {(p.file, p.element_id) for p in report.invalid}
    assert {(path, RENAMED[0]), (path, REMOVED)} <= invalid
    assert {element_id for _, element_id in invalid} == {RENAMED[0], REMOVED}
    assert all(p.code == "unknown-element" for p in report.invalid)
    # The manifest knows the rename, so the hint names the new entity.
    # No page replaces the removed page, so its hint comes from the spelling.
    hints = {p.element_id: p.hint for p in report.invalid}
    assert hints[RENAMED[0]] == f"Did you mean '{RENAMED[1]}'?"
    assert hints[REMOVED] == "Did you mean 'pages.projects'?"


def test_the_orphans_command_lists_the_old_extension_file_and_the_new_element(
    tmp_path: Path, changed: AppDefinition
) -> None:
    fastapi = find_binding("fastapi")
    original = load_definition_text(EXAMPLE.read_text(), str(EXAMPLE))
    write_result(generate(original, fastapi), tmp_path, "fastapi")
    write_result(generate(changed, fastapi), tmp_path, "fastapi")
    changed_file = tmp_path / "changed.yaml"
    changed_file.write_text(change(EXAMPLE.read_text()))
    shutil.copytree(EXAMPLE.parent / "apis", tmp_path / "apis")
    shutil.copytree(EXAMPLE.parent / "webhooks", tmp_path / "webhooks")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    runner = CliRunner()
    text = runner.invoke(app, ["orphans", str(changed_file), str(tmp_path)])
    data = runner.invoke(app, ["orphans", str(changed_file), str(tmp_path), "-f", "json"])

    assert text.exit_code == 0, text.output
    assert text.output == (
        "Orphaned extension files: 1\n"
        "  app/features/comments/validation_ext.py: entities.Comment\n"
        "    suggestion: move the code to the element 'entities.Remark'.\n"
    )
    assert json.loads(data.output) == {
        "version": 1,
        "orphans": [
            {
                "file": "app/features/comments/validation_ext.py",
                "element_id": "entities.Comment",
                "suggestion": "entities.Remark",
            }
        ],
    }
    # The command changes no file.
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    manifest = read_manifest(tmp_path)
    assert manifest is not None
    assert render_orphans(find_orphans(changed, tmp_path, manifest), "text") == text.output


def test_a_new_run_keeps_the_migrations_of_the_fastapi_app(
    tmp_path: Path, changed: AppDefinition
) -> None:
    binding = find_binding("fastapi")
    original = load_definition_text(EXAMPLE.read_text(), str(EXAMPLE))
    report = write_result(generate(original, binding), tmp_path, "fastapi")
    first = tmp_path / "migrations" / "versions" / "0001_schema.py"
    assert "migrations/versions/0001_schema.py" in report.created_extensions
    schema = first.read_text()
    # The app developer makes the next migration (alembic revision --autogenerate).
    second = tmp_path / "migrations" / "versions" / "0002_project_priority.py"
    second.write_text('"""Add the priority of a project."""\n')

    report = write_result(generate(changed, binding), tmp_path, "fastapi")

    # The first migration keeps the schema of the first run, and the next one stays.
    assert "migrations/versions/0001_schema.py" in report.kept_extensions
    assert first.read_text() == schema
    assert second.read_text() == '"""Add the priority of a project."""\n'
    # The models follow the changed definition.
    assert "priority" in (tmp_path / "app" / "features" / "projects" / "models.py").read_text()
    # The first migration has no traces of elements, so the changes make none invalid.
    invalid = check_traces(changed, tmp_path).invalid
    assert [p for p in invalid if p.file.startswith("migrations/")] == []


def test_a_generated_first_migration_of_an_older_run_stays(tmp_path: Path) -> None:
    """Before ADR 0009, the first migration was a generated file. A new run keeps it."""
    binding = find_binding("fastapi")
    original = load_definition_text(EXAMPLE.read_text(), str(EXAMPLE))
    result = generate(original, binding)
    old = [
        replace(f, kind="generated") if f.path.endswith("0001_schema.py") else f
        for f in result.files
    ]
    write_result(replace(result, files=old), tmp_path, "fastapi")
    first = tmp_path / "migrations" / "versions" / "0001_schema.py"
    first.write_text(first.read_text() + "# The schema of the first run.\n")

    report = write_result(result, tmp_path, "fastapi", force=True)

    assert "migrations/versions/0001_schema.py" not in report.deleted
    assert first.read_text().endswith("# The schema of the first run.\n")
