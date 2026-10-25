"""`scripts/evaluate_skill.py` prepares and scores the agent tasks of the skill evaluation.

For each task, the test prepares a work folder, scores it as it is (the
task is not solved), solves the task as an agent does, and scores it
again. The tests skip the tests of the generated apps (`--no-app-tests`),
and run no agent.
"""

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "evaluate_skill.py"
TASKS = ROOT / "docs" / "evaluation" / "skill-tasks"


def evaluate(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(a) for a in args)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )


def appgen(*args: str | Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "appgen", *(str(a) for a in args)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def score(folder: Path) -> dict[str, Any]:
    result = evaluate("score", folder, "--no-app-tests")
    data: dict[str, Any] = json.loads(result.stdout)
    assert result.returncode == (0 if data["passed"] else 1)
    assert json.loads((folder / "score.json").read_text(encoding="utf-8")) == data
    return data


TOOL_LIBRARY = """\
version: 0
app: { name: tool-library, title: Tool Library }
entities:
  Member:
    crud: true
    display_field: name
    fields:
      name: { type: string, required: true, max_length: 120 }
  Tool:
    crud: true
    display_field: name
    fields:
      name: { type: string, required: true, max_length: 120 }
      category: { type: enum, values: [garden, kitchen, workshop], required: true }
      condition_note: { type: text }
  Loan:
    crud: true
    fields:
      loaned_on: { type: date, required: true }
      due_on: { type: date, required: true }
      returned_on: { type: date }
    relations:
      member: { kind: many_to_one, target: Member, required: true }
      tool: { kind: many_to_one, target: Tool, required: true }
"""


def solve_new_definition(work: Path) -> None:
    (work / "app.yaml").write_text(TOOL_LIBRARY, encoding="utf-8")
    appgen("generate", work / "app.yaml", "-b", "fastapi", "-o", work / "app")


def solve_change_definition(work: Path) -> None:
    definition = work / "app.yaml"
    text = definition.read_text(encoding="utf-8")
    text = re.sub(r"\bMember\b", "Person", text)
    text = re.sub(r"\blist_members\b", "list_persons", text)
    text = re.sub(r"\b(\w+)_member\b", r"\1_person", text)
    text = re.sub(r"\bmember_(table|detail)\b", r"person_\1", text)
    email = "      email: { type: email, required: true, unique: true }\n"
    assert email in text
    text = text.replace(email, email + "      phone: { type: string, max_length: 30 }\n", 1)
    definition.write_text(text, encoding="utf-8")
    appgen("generate", definition, "-b", "fastapi", "-o", work / "app")
    # The hand-written code, and the stubs that import the model of the user.
    for code in (work / "app" / "app").rglob("*_ext.py"):
        text = code.read_text(encoding="utf-8")
        text = re.sub(r"\bMember\b", "Person", text.replace(".members.", ".persons."))
        code.write_text(text, encoding="utf-8")
    orphans = json.loads(appgen("orphans", definition, work / "app", "-f", "json").stdout)
    for orphan in orphans["orphans"]:
        (work / "app" / orphan["file"]).unlink()
    appgen("generate", definition, "-b", "fastapi", "-o", work / "app")


def solve_fill_gaps(work: Path) -> None:
    operation = work / "app" / "src" / "features" / "complete-task" / "api" / "complete-task.ext.ts"
    operation.write_text(
        "// Created by appgen once. appgen never changes or deletes this file.\n"
        "// @trace:manual operations.complete_task file\n"
        'import "server-only";\n\n'
        'import type { Task } from "@/entities/task";\n'
        'import { taskRepository } from "@/entities/task/server";\n\n'
        "export async function completeTask(record: Task): Promise<Task> {\n"
        '  return taskRepository.update(record.id, { status: "done" });\n'
        "}\n",
        encoding="utf-8",
    )
    widget = work / "app" / "src" / "widgets" / "overview" / "ui" / "workload-widget.ext.tsx"
    widget.write_text(
        "// Created by appgen once. appgen never changes or deletes this file.\n"
        "// @trace:manual ui.dashboards.overview.widgets.workload file\n"
        "export function WorkloadWidget() {\n"
        "  return <p>0</p>;\n"
        "}\n",
        encoding="utf-8",
    )


ROOM_SEED = """\
seed:
  Amenity:
    records:
      screen: { name: Screen }
      board: { name: Whiteboard }
      call: { name: Video conference }
  Room:
    records:
      atlas: { name: Atlas, floor: 1, capacity: 8, hourly_rate: 25.00, amenities: [screen, board] }
      borealis: { name: Borealis, floor: 1, capacity: 4, amenities: [board] }
      cassini:
        name: Cassini
        floor: 2
        capacity: 12
        hourly_rate: 40.50
        amenities: [screen, call]
      dione: { name: Dione, floor: 3, capacity: 2, hourly_rate: 10 }
      europa:
        name: Europa
        floor: 3
        capacity: 20
        hourly_rate: 60
        amenities: [screen, board, call]
"""


def solve_seed_csv(work: Path) -> None:
    definition = work / "app.yaml"
    text = definition.read_text(encoding="utf-8")
    definition.write_text(text.rstrip("\n") + "\n\n" + ROOM_SEED, encoding="utf-8")
    appgen("generate", definition, "-b", "react", "-o", work / "app")


SOLUTIONS: dict[str, Callable[[Path], None]] = {
    "new-definition": solve_new_definition,
    "change-definition": solve_change_definition,
    "fill-gaps": solve_fill_gaps,
    "seed-csv": solve_seed_csv,
}


def test_each_task_has_a_prompt_and_a_solution_in_the_test() -> None:
    result = evaluate("prepare", "--help")

    tasks = re.search(r"\{([a-z,-]+)\}", result.stdout)
    assert tasks
    assert sorted(tasks.group(1).split(",")) == sorted(p.stem for p in TASKS.glob("*.md"))
    assert set(SOLUTIONS) == set(tasks.group(1).split(","))


@pytest.mark.parametrize("task", sorted(SOLUTIONS))
def test_prepare_and_score_an_unsolved_and_a_solved_task(task: str, tmp_path: Path) -> None:
    folder = tmp_path / task

    prepared = evaluate("prepare", task, folder)

    assert prepared.returncode == 0, prepared.stderr
    prompt = " ".join((TASKS / f"{task}.md").read_text(encoding="utf-8").split())
    assert prepared.stdout.strip() == prompt
    info = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    assert info["task"] == task
    assert info["prompt"] == prompt
    assert set(info) >= {"appgen", "commit", "prepared", "binding"}
    # The home folder has only the installed skill.
    assert sorted(p.name for p in (folder / "home").iterdir()) == [".agents", ".claude"]
    assert (folder / "home" / ".claude" / "skills" / "appgen" / "SKILL.md").is_file()

    unsolved = score(folder)

    assert unsolved["passed"] is False
    assert unsolved["problems"]
    assert unsolved["checks"]["app_tests"] is None

    SOLUTIONS[task](folder / "work")
    solved = score(folder)

    assert solved["problems"] == []
    assert solved["passed"] is True
    assert solved["files_written_by_a_new_run"] == 0

    table = evaluate("report", folder).stdout
    assert table.splitlines()[2].startswith(f"| {task} | {task} | - |")
    assert table.splitlines()[2].endswith("| yes | yes | yes | yes | - | yes | yes |")


def test_score_finds_a_manual_edit_and_an_invalid_trace(tmp_path: Path) -> None:
    folder = tmp_path / "fill-gaps"
    evaluate("prepare", "fill-gaps", folder)
    solve_fill_gaps(folder / "work")
    manifest = json.loads((folder / "work" / "app" / ".appgen" / "manifest.json").read_text())
    page = folder / "work" / "app" / next(p for p in manifest["generated"] if p.endswith(".tsx"))
    page.write_text(page.read_text(encoding="utf-8") + "// A manual edit.\n", encoding="utf-8")
    note = folder / "work" / "app" / "src" / "note.ts"
    note.write_text("// @trace entities.Nothing\n", encoding="utf-8")

    result = score(folder)

    assert result["checks"]["no_manual_edits"] is False
    assert result["checks"]["no_invalid_traces"] is False
    assert result["passed"] is False


def test_score_finds_an_app_that_is_not_generated_again(tmp_path: Path) -> None:
    folder = tmp_path / "seed-csv"
    evaluate("prepare", "seed-csv", folder)
    definition = folder / "work" / "app.yaml"
    definition.write_text(definition.read_text(encoding="utf-8") + ROOM_SEED, encoding="utf-8")

    result = score(folder)

    assert result["checks"]["no_manual_edits"] is False
    assert result["files_written_by_a_new_run"] > 0
    assert any("not generated from the last definition" in p for p in result["problems"])


def test_prepare_stops_at_a_folder_that_is_not_empty(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    result = evaluate("prepare", "fill-gaps", tmp_path)

    assert result.returncode != 0
    assert "is not empty" in result.stderr
