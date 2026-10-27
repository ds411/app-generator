"""`scripts/evaluate_skill.py` prepares and scores the agent tasks of the skill evaluation.

For each task, the test prepares a work folder, scores it as it is (the
task is not solved), solves the task as an agent does, and scores it
again. The tests skip the tests of the generated apps (`--no-app-tests`),
and run no agent: a fake `claude` command checks the sessions of a task
with more than one prompt.
"""

import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from skill_support import QUICKSTART, fenced_blocks

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "evaluate_skill.py"
TASKS = ROOT / "docs" / "evaluation" / "skill-tasks"


def load_script() -> ModuleType:
    """Load `scripts/evaluate_skill.py`: the folder `scripts` is not a package."""
    spec = importlib.util.spec_from_file_location("evaluate_skill", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = load_script()


def prompts(task: str) -> list[str]:
    text = (TASKS / f"{task}.md").read_text(encoding="utf-8")
    return [" ".join(part.split()) for part in text.split("\n---\n")]


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


def record(*rows: str) -> str:
    """Return the record of the defaults at the top of a definition, as the skill tells."""
    lines = [
        f'# - {row}: the choice of the agent. Prompt: "the words of the prompt"' for row in rows
    ]
    return "\n".join(["# appgen-quickstart defaults:", *lines, ""])


def with_sign_in(definition: str) -> str:
    """Add a sign-in with an email address to the definition of the tool library."""
    email = "      email: { type: email, required: true, unique: true }\n"
    text = definition.replace("max_length: 120 }\n", "max_length: 120 }\n" + email, 1)
    return text + "auth: { user_entity: Member, username_field: email }\n"


def solve_quickstart_tool_library(work: Path) -> None:
    definition = work / "app.yaml"
    definition.write_text(record("binding", "app", "auth") + with_sign_in(TOOL_LIBRARY))
    appgen("generate", definition, "-b", "nextjs", "-o", work / "nextjs")


def solve_quickstart_mobile_api(work: Path) -> None:
    definition = work / "app.yaml"
    definition.write_text(record("binding", "auth") + with_sign_in(TOOL_LIBRARY))
    appgen("generate", definition, "-b", "fastapi", "-o", work / "fastapi")


HELP_DESK = """\
version: 0
app: { name: it-help-desk, title: IT Help Desk }
auth:
  user_entity: Person
  username_field: email
  password: false
  providers:
    company:
      title: Company account
      issuer: https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_Hd7Qm2xYz
      client_id_env: COMPANY_CLIENT_ID
      client_secret_env: COMPANY_CLIENT_SECRET
      authorize_params: { identity_provider: EntraID }
      trust_email: true
      create_users: true
      claims: { name: name }
entities:
  Person:
    display_field: name
    fields:
      name: { type: string, required: true, max_length: 120 }
      email: { type: email, required: true, unique: true }
  Ticket:
    crud: true
    display_field: title
    fields:
      title: { type: string, required: true, max_length: 200 }
      status: { type: enum, values: [open, closed], default: open }
apis:
  jira:
    document: jira.openapi.json
    base_url_env: JIRA_API_URL
    security: { scheme: basicAuth, username_env: JIRA_EMAIL, env: JIRA_API_TOKEN }
    operations: [searchAndReconsileIssuesUsingJql]
"""
"""A help desk whose staff sign in with Entra ID through Cognito, and that calls Jira."""


def solve_quickstart_company_jira(work: Path) -> None:
    definition = work / "app.yaml"
    rows = ("binding", "auth", "providers", "password", "apis")
    definition.write_text(record(*rows) + HELP_DESK, encoding="utf-8")
    appgen("generate", definition, "-b", "nextjs", "-o", work / "nextjs")


RETURN_LOAN = {
    "nextjs": "nextjs/src/features/return-loan/api/return-loan.ext.ts",
    "fastapi": "fastapi/app/features/loans/return_loan_ext.py",
}
"""The extension files of the custom operation `return_loan`, by binding."""


def solve_quickstart_change_bindings(work: Path) -> None:
    definition = work / "app.yaml"
    operation = (
        "operations:\n"
        "  return_loan:\n"
        "    { kind: custom, entity: Loan, description: Return a tool., returns: Loan }\n"
    )
    # The first prompt: a Next.js app, and the logic of the custom operation.
    definition.write_text(record("binding") + TOOL_LIBRARY + operation, encoding="utf-8")
    appgen("generate", definition, "-b", "nextjs", "-o", work / "nextjs")
    fill(work / RETURN_LOAN["nextjs"], "//")
    # The second prompt: React with the FastAPI app, and the logic again in Python.
    text = definition.read_text(encoding="utf-8")
    text = text.replace(
        "app: { name: tool-library,", 'app: { "x-react-data": api, name: tool-library,'
    )
    definition.write_text(text, encoding="utf-8")
    for binding in ("react", "fastapi"):
        appgen("generate", definition, "-b", binding, "-o", work / binding)
    fill(work / RETURN_LOAN["fastapi"], "#")


def fill(extension: Path, comment: str) -> None:
    """Change the trace of a gap file to a manual trace, as hand-written code does."""
    text = extension.read_text(encoding="utf-8")
    assert f"{comment} @trace:gap operations.return_loan" in text
    extension.write_text(text.replace("@trace:gap", "@trace:manual"), encoding="utf-8")


SOLUTIONS: dict[str, Callable[[Path], None]] = {
    "new-definition": solve_new_definition,
    "change-definition": solve_change_definition,
    "fill-gaps": solve_fill_gaps,
    "seed-csv": solve_seed_csv,
    "quickstart-tool-library": solve_quickstart_tool_library,
    "quickstart-mobile-api": solve_quickstart_mobile_api,
    "quickstart-company-jira": solve_quickstart_company_jira,
    "quickstart-change-bindings": solve_quickstart_change_bindings,
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
    assert prepared.stdout.splitlines() == prompts(task)
    info = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    assert info["task"] == task
    assert info["prompts"] == prompts(task)
    assert set(info) >= {"appgen", "commit", "prepared", "binding", "apps"}
    # The home folder has only the installed skills.
    assert sorted(p.name for p in (folder / "home").iterdir()) == [".agents", ".claude"]
    for skill in ("appgen", "appgen-quickstart"):
        assert (folder / "home" / ".claude" / "skills" / skill / "SKILL.md").is_file()
    if task.startswith("quickstart-"):
        # Only the files that the prompts name, for example an OpenAPI document.
        files = script.TASK_BY_NAME[task].files
        assert sorted(p.name for p in (folder / "work").iterdir()) == sorted(files)

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
    defaults = "yes" if task.startswith("quickstart-") else "-"
    assert table.splitlines()[2].endswith(f"| yes | yes | yes | yes | - | {defaults} | yes | yes |")


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


def test_the_record_check_reads_the_record_of_the_skill() -> None:
    (example,) = fenced_blocks((QUICKSTART / "SKILL.md").read_text(encoding="utf-8"), "yaml")

    rows, problems = script.record_rows(example)

    assert problems == []
    assert rows[:2] == ["binding", "app"]
    assert script.record_rows("version: 0\n")[1] == [
        "app.yaml has no record of the defaults: no line '# appgen-quickstart defaults:'"
    ]
    rows, problems = script.record_rows(record("binding") + "# - auth: no words\nversion: 0\n")
    assert rows == ["binding"]
    assert problems == [
        "a line of the record does not have the format of the skill: # - auth: no words"
    ]


def test_the_key_check_reads_names_values_and_missing_keys() -> None:
    data = {
        "app": {"x-react-data": "api"},
        "auth": {"password": False, "providers": {"company": {"trust_email": True}}},
    }

    assert script.key_problem(data, "app.x-react-data: api") is None
    assert script.key_problem(data, "auth.password: false") is None
    assert script.key_problem(data, "auth.providers.<>.trust_email: true") is None
    assert script.key_problem(data, "!apis") is None
    assert script.key_problem(data, "app.x-react-data: mock") == (
        "the definition has app.x-react-data: api, not mock"
    )
    assert script.key_problem(data, "auth.user_entity") == "the definition has no auth.user_entity"
    assert script.key_problem(data, "!auth.providers") == "the definition has auth.providers"


def test_score_finds_defaults_that_do_not_agree_with_the_task(tmp_path: Path) -> None:
    folder = tmp_path / "quickstart-tool-library"
    evaluate("prepare", "quickstart-tool-library", folder)
    work = folder / "work"
    # A React app in the folder of the Next.js app, a FastAPI app, a sign-in with a
    # provider, and no record of the defaults.
    providers = (
        "  providers:\n"
        "    company:\n"
        "      issuer: https://login.example.com\n"
        "      client_id_env: COMPANY_CLIENT_ID\n"
        "      client_secret_env: COMPANY_CLIENT_SECRET\n"
    )
    text = with_sign_in(TOOL_LIBRARY).replace(
        "auth: { user_entity: Member, username_field: email }", ""
    )
    text += "auth:\n  user_entity: Member\n  username_field: email\n" + providers
    (work / "app.yaml").write_text(text, encoding="utf-8")
    appgen("generate", work / "app.yaml", "-b", "react", "-o", work / "nextjs")
    appgen("generate", work / "app.yaml", "-b", "fastapi", "-o", work / "fastapi")

    result = score(folder)

    assert result["checks"]["defaults"] is False
    assert result["passed"] is False
    assert {
        "the folder nextjs has no app of the binding nextjs",
        "the folder fastapi has an app that the task does not expect",
        "the definition has auth.providers",
        "app.yaml has no record of the defaults: no line '# appgen-quickstart defaults:'",
        "the record of the defaults has no row binding, app, auth",
    } <= set(result["problems"])


FAKE_CLAUDE = """\
import json, sys

with open(sys.argv[0] + ".calls", "a", encoding="utf-8") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
resumed = "--resume" in sys.argv
session = sys.argv[sys.argv.index("--resume") + 1] if resumed else "s-1"
print(json.dumps({"type": "system", "subtype": "init", "session_id": session, "model": "m"}))
# After --resume, the total cost includes the cost of the earlier prompts.
print(json.dumps({
    "type": "result", "session_id": session, "num_turns": 3, "duration_ms": 2000,
    "total_cost_usd": 0.5 if resumed else 0.25, "is_error": False,
    "model_usage_since_last_result": {"m": {"costUSD": 0.25}}, "result": "Done: " + sys.argv[2],
}))
"""


def test_run_sends_each_prompt_in_the_same_session(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    claude.write_text(f"#!{sys.executable}\n" + FAKE_CLAUDE, encoding="utf-8")
    claude.chmod(0o755)
    folder = tmp_path / "run"
    evaluate("prepare", "quickstart-change-bindings", folder)

    result = evaluate("run", folder, "--model", "m", "--claude", claude)

    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (tmp_path / "claude.calls").read_text().splitlines()]
    first, second = prompts("quickstart-change-bindings")
    assert [call[:2] for call in calls] == [["-p", first], ["-p", second]]
    assert "--resume" not in calls[0]
    assert calls[1][2:4] == ["--resume", "s-1"]
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert (run["turns"], run["duration_s"], run["cost_usd"]) == (6, 4, 0.5)
    assert run["results"] == [f"Done: {first}", f"Done: {second}"]
    assert run["exit_code"] == 0
