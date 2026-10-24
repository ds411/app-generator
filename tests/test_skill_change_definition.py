"""An agent follows the steps of `change-definition.md` on the project tracker (ADR 0015).

The tests use the CLI, as an agent does. They fill a gap of the FastAPI
app, rename a field that the hand-written code uses, and rename an entity
with a hand-written extension file. After the steps of the reference,
the checker reports no invalid traces.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from skill_support import ROOT, SKILL
from typer.testing import CliRunner

from appgen.cli import app

EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"
CHANGE_DEFINITION = SKILL / "references" / "change-definition.md"
OPERATION = "app/features/tasks/complete_task_ext.py"
VALIDATION = "app/features/comments/validation_ext.py"
runner = CliRunner()


def appgen(*args: str | Path) -> Any:
    """Run appgen, and return the JSON output, or the text for a command without JSON."""
    result = runner.invoke(app, [str(a) for a in args])
    assert result.exit_code in (0, 1), result.output
    return json.loads(result.output) if "json" in args else result.output


def fill_the_gap(folder: Path) -> None:
    """Write the logic of complete_task, as fill-gaps.md tells."""
    path = folder / OPERATION
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "@trace:gap operations.complete_task", "@trace:manual operations.complete_task"
    )
    text = text.replace(
        "    # TODO(appgen): write the logic of the operation complete_task.\n"
        '    raise NotImplementedError("operations.complete_task")\n',
        '    record.status = "done"\n'
        "    # @trace:manual entities.Task.fields.completed_at\n"
        "    record.completed_at = datetime.now(UTC)\n"
        "    return record\n",
    )
    text = text.replace('"""\n\nfrom ', '"""\n\nfrom datetime import UTC, datetime\n\nfrom ', 1)
    assert "TODO(appgen)" not in text
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def tracker(tmp_path: Path) -> tuple[Path, Path]:
    """Return the definition and the FastAPI app of the project tracker, with a filled gap."""
    definition = tmp_path / "app.yaml"
    shutil.copy(EXAMPLE, definition)
    folder = tmp_path / "app"
    appgen("generate", definition, "-b", "fastapi", "-o", folder)
    fill_the_gap(folder)
    report = appgen("check", definition, folder, "--format", "json")
    assert report["invalid"] == []
    assert "operations.complete_task" not in [g["id"] for g in report["gaps"]]
    return definition, folder


def rename(definition: Path, old: str, new: str) -> None:
    """Step 3: rename a name and each reference to it in the definition."""
    text = definition.read_text(encoding="utf-8")
    definition.write_text(re.sub(rf"\b{old}\b", new, text), encoding="utf-8")


def generate_and_check(definition: Path, folder: Path) -> dict[str, Any]:
    """Steps 4 to 6: validate, generate into the same folder, and check."""
    assert appgen("validate", definition, "--format", "json")["diagnostics"] == []
    appgen("generate", definition, "-b", "fastapi", "-o", folder)
    return appgen("check", definition, folder, "--format", "json")


def test_a_renamed_field_of_hand_written_code_gets_the_id_of_the_hint(
    tracker: tuple[Path, Path],
) -> None:
    definition, folder = tracker

    rename(definition, "completed_at", "finished_at")
    report = generate_and_check(definition, folder)

    # The hand-written code keeps the old field. The check shows the drift.
    (problem,) = report["invalid"]
    assert problem["file"] == OPERATION
    assert problem["code"] == "unknown-element"
    assert problem["hint"] == "Did you mean 'entities.Task.fields.finished_at'?"
    # A field has no extension file, so no file is orphaned.
    assert appgen("orphans", definition, folder, "--format", "json")["orphans"] == []

    # Step 5 of "Rename an element": change the trace to the ID of the hint, and the code.
    new_id = problem["hint"].split("'")[1]
    path = folder / OPERATION
    code = path.read_text(encoding="utf-8")
    path.write_text(
        code.replace(problem["element_id"], new_id).replace(".completed_at", ".finished_at"),
        encoding="utf-8",
    )

    report = appgen("check", definition, folder, "--format", "json")
    assert report["invalid"] == []
    assert "finished_at" in (folder / "app" / "features" / "tasks" / "models.py").read_text()


def test_the_code_of_a_renamed_entity_moves_to_the_extension_file_of_the_new_entity(
    tracker: tuple[Path, Path],
) -> None:
    definition, folder = tracker
    old_file = folder / VALIDATION
    rule = (
        "    # @trace:manual entities.Comment.fields.body\n"
        "    if not record.body.strip():\n"
        '        raise ProblemError(422, "A comment needs a text.")\n'
    )
    old_file.write_text(old_file.read_text(encoding="utf-8") + rule, encoding="utf-8")
    assert appgen("check", definition, folder, "--format", "json")["invalid"] == []

    rename(definition, "Comment", "Remark")
    # The CRUD shorthand names its operations after the entity, so the
    # references to the old operations are not valid any more.
    diagnostics = appgen("validate", definition, "--format", "json")["diagnostics"]
    assert {d["code"] for d in diagnostics} == {"unknown-reference"}
    assert any("create_comment" in d["message"] for d in diagnostics)
    for operation in ("create", "read", "update", "delete"):
        rename(definition, f"{operation}_comment", f"{operation}_remark")
    rename(definition, "list_comments", "list_remarks")
    report = generate_and_check(definition, folder)

    assert {p["file"] for p in report["invalid"]} == {VALIDATION}
    assert {p["code"] for p in report["invalid"]} == {"unknown-element"}
    (orphan,) = appgen("orphans", definition, folder, "--format", "json")["orphans"]
    assert orphan == {
        "file": VALIDATION,
        "element_id": "entities.Comment",
        "suggestion": "entities.Remark",
    }

    # Steps 2 to 4: move the code to the extension file of the new element,
    # change its traces, and delete the old file.
    new_file = folder / "app" / "features" / "remarks" / "validation_ext.py"
    assert new_file.is_file()
    moved = rule.replace("entities.Comment", orphan["suggestion"]).replace("comment", "remark")
    new_file.write_text(new_file.read_text(encoding="utf-8") + moved, encoding="utf-8")
    old_file.unlink()
    appgen("generate", definition, "-b", "fastapi", "-o", folder)

    report = appgen("check", definition, folder, "--format", "json")
    assert report["invalid"] == []
    assert appgen("orphans", definition, folder, "--format", "json")["orphans"] == []


def test_the_generator_stops_at_a_manual_edit_until_the_edit_moves(
    tracker: tuple[Path, Path],
) -> None:
    definition, folder = tracker
    generated = folder / "app" / "features" / "tasks" / "schemas.py"
    original = generated.read_text(encoding="utf-8")
    generated.write_text(original + "# A manual edit.\n", encoding="utf-8")

    result = runner.invoke(app, ["generate", str(definition), "-b", "fastapi", "-o", str(folder)])

    assert result.exit_code == 1
    assert "changed by hand: app/features/tasks/schemas.py" in result.output
    # After the edit moves to an extension file, --force writes the generated file again.
    appgen("generate", definition, "-b", "fastapi", "-o", folder, "--force")
    assert generated.read_text(encoding="utf-8") == original


def test_the_reference_gives_the_steps_of_the_tests() -> None:
    text = CHANGE_DEFINITION.read_text(encoding="utf-8")

    for words in (
        "appgen check app.yaml <dir> --format json",
        "appgen orphans app.yaml <dir> --format json",
        "Generate into the same folder",
        "`@trace:manual <new ID> file`",
        "Delete the old file",
        "`--force`",
        "Never edit a generated file",
    ):
        assert words in text
