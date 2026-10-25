"""Prepare, run, and score the agent tasks of the evaluation of the skill.

`docs/evaluation-skills.md` gives the results. The prompt of each task is
in `docs/evaluation/skill-tasks/<task>.md`. A run uses one folder:

- `work/`: the folder of the agent. It has the definition and the app
  that the task starts from, and nothing else.
- `home/`: an empty home folder with the installed skill
  (`appgen skills install --scope user`), so that the appgen skill is the
  only skill of the agent.
- `task.json`, `log.jsonl` (the session), `run.json`, and `score.json`:
  the files of the evaluation, outside the folder of the agent.

Commands, from the root of the repository:

    uv run scripts/evaluate_skill.py prepare <task> <folder>
    uv run scripts/evaluate_skill.py run <folder> --model <model>
    uv run scripts/evaluate_skill.py score <folder> [--no-app-tests]
    uv run scripts/evaluate_skill.py report <folder>...

`prepare` makes the folder and prints the prompt. `run` starts Claude Code
in print mode in `work/`, with `home/` as the home folder, and writes
`log.jsonl` and `run.json` (the turns, the time, the cost, and the number
of `appgen validate` runs). The agent runs the `appgen` of its PATH:
install the appgen of the checkout first, with `uv tool install --force .`.
The run keeps the package caches of uv and pnpm of the real home folder.
The runs cost money, so no test and no hook runs `run`.

`score` writes `score.json`: the definition is valid, `appgen check`
reports no invalid traces, the expected gaps are closed, a new
`appgen generate` into a copy of the app writes no file (no generated
file has manual edits, and the app is generated from the last
definition), the tests of the app pass, and the checks of the task pass
(for example, the renamed entity exists). `--no-app-tests`
skips the tests of the app. `report` prints a Markdown table of runs.
"""

import argparse
import csv
import datetime
import decimal
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from appgen.dsl import DefinitionError, load_definition

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "docs" / "evaluation" / "skill-tasks"
EXAMPLES = ROOT / "examples"
APP = "app"
ALL_GAPS = ("*",)
"""The expected gaps of a task whose app must have no open gap."""
CHECK_TITLES = {
    "valid": "Valid",
    "no_invalid_traces": "No invalid traces",
    "gaps_closed": "Gaps closed",
    "no_manual_edits": "No manual edits",
    "app_tests": "App tests",
    "task": "Task checks",
}
"""The checks of score.json, with their titles in the report."""
KEEP_VARIABLES = {"CLAUDE_SESSION_INGRESS_TOKEN_FILE"}
"""The variables of a Claude Code cloud session that a run needs."""

type Definition = dict[str, Any]


def appgen(*args: str | Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the appgen of this checkout."""
    return subprocess.run(
        [sys.executable, "-m", "appgen", *(str(a) for a in args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def appgen_json(*args: str | Path, cwd: Path | None = None) -> Any:
    result = appgen(*args, cwd=cwd)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


# The tasks.

CANCEL_BOOKING = '''\
# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.cancel_booking file
"""The logic of the operation `cancel_booking`.

Cancel a booking, and tell the organizer.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.bookings.models import Booking
from app.features.bookings.schemas import CancelBookingParams

logger = logging.getLogger(__name__)


async def cancel_booking(
    session: AsyncSession,
    record: Booking,
    params: CancelBookingParams,
) -> Booking:
    """Set the booking to cancelled, and tell the organizer."""
    record.status = "cancelled"
    await session.refresh(record, ["organizer"])
    # @trace:manual entities.Member.fields.email
    logger.info("Tell %s: the booking is cancelled. %s", record.organizer.email, params.reason)
    return record
'''
"""The hand-written logic of `cancel_booking` before the task `change-definition`."""

ROOMS_CSV = """\
Room,Floor,Seats,Rate per hour (EUR),Equipment
Atlas,1,8,25.00,Screen; Whiteboard
Borealis,1,4,,Whiteboard
Cassini,2,12,40.50,Screen; Video conference
Dione,3,2,10,
Europa,3,20,60,Screen; Whiteboard; Video conference
"""
"""The export of the rooms of the task `seed-csv`."""
ROOM_COLUMNS = {"floor": "Floor", "capacity": "Seats", "hourly_rate": "Rate per hour (EUR)"}
"""The number fields of the entity Room, with their columns in the export."""


def _mapping(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _names(definition: Definition, section: str) -> list[str]:
    return list(_mapping(definition.get(section)))


def _entity(definition: Definition, name: str) -> dict[str, Any]:
    return _mapping(_mapping(definition.get("entities")).get(name))


def check_new_definition(work: Path, definition: Definition) -> list[str]:
    problems: list[str] = []
    entities = [name.lower() for name in _names(definition, "entities")]
    for word in ("member", "tool", "loan"):
        if not any(word in name for name in entities):
            problems.append(f"no entity for the word '{word}'")
    tool = next((n for n in _names(definition, "entities") if "tool" in n.lower()), None)
    fields = _mapping(_entity(definition, tool).get("fields")) if tool else {}
    categories = [
        set(_mapping(f).get("values") or [])
        for f in fields.values()
        if _mapping(f).get("type") == "enum"
    ]
    if not any({"garden", "kitchen", "workshop"} <= values for values in categories):
        problems.append("no enum field of the tool with the values garden, kitchen, and workshop")
    return problems


def check_change_definition(work: Path, definition: Definition) -> list[str]:
    problems: list[str] = []
    if "Member" in _names(definition, "entities"):
        problems.append("the entity Member exists")
    person = _entity(definition, "Person")
    if not person:
        problems.append("no entity Person")
    elif "phone" not in (person.get("fields") or {}):
        problems.append("the entity Person has no field phone")
    code = work / APP / "app" / "features" / "bookings" / "cancel_booking_ext.py"
    text = code.read_text(encoding="utf-8") if code.is_file() else ""
    if (
        'record.status = "cancelled"' not in text
        or "@trace:manual operations.cancel_booking" not in text
    ):
        problems.append("the hand-written code of cancel_booking is gone")
    if "entities.Person.fields.email" not in text:
        problems.append("the trace of the hand-written code does not refer to Person")
    orphans = appgen_json("orphans", work / "app.yaml", work / APP, "-f", "json")
    if orphans is None or orphans["orphans"]:
        problems.append("appgen orphans lists files, or fails")
    return problems


def check_fill_gaps(work: Path, definition: Definition) -> list[str]:
    return []


def csv_rooms() -> list[dict[str, str]]:
    return list(csv.DictReader(ROOMS_CSV.splitlines()))


def _number(text: object) -> decimal.Decimal | None:
    try:
        return decimal.Decimal(str(text)) if text not in (None, "") else None
    except decimal.InvalidOperation:
        return None


def check_seed_csv(work: Path, definition: Definition) -> list[str]:
    """Compare the seed records of Room with rooms.csv, and the mock data of the app with them.

    The columns of the export are not the field names, so the agent must
    map them: Room to `name`, Floor to `floor`, Seats to `capacity`, the
    rate to `hourly_rate`, and the equipment to the relation `amenities`.
    """
    try:
        loaded = load_definition(work / "app.yaml")
    except DefinitionError:
        return ["the definition does not load"]
    rooms = loaded.seed.get("Room")
    amenities = loaded.seed.get("Amenity")
    records = {r.values.get("name"): r.values for r in rooms.records.values()} if rooms else {}
    amenity_names = (
        {key: r.values.get("name") for key, r in amenities.records.items()} if amenities else {}
    )
    problems: list[str] = []
    expected = csv_rooms()
    names = {room["Room"] for room in expected}
    if set(records) != names:
        problems.append(
            f"the seed records of Room are {sorted(map(str, records))}, not {sorted(names)}"
        )
    for room in expected:
        values = records.get(room["Room"])
        if values is None:
            continue
        wrong = [
            name
            for name, column in ROOM_COLUMNS.items()
            if _number(values.get(name)) != _number(room[column])
        ]
        equipment = {e.strip() for e in room["Equipment"].split(";") if e.strip()}
        keys = cast(list[str], values.get("amenities") or [])
        if {amenity_names.get(k) for k in keys} != equipment:
            wrong.append("amenities")
        if wrong:
            problems.append(
                f"the seed record of the room {room['Room']} has wrong {', '.join(wrong)}"
            )
    mock = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (work / APP / "src").rglob("*mock-data.ts")
        if path.is_file()
    )
    for name in sorted(names):
        if f'"{name}"' not in mock:
            problems.append(f"the mock data of the React app has no room {name}")
    return problems


@dataclass(frozen=True)
class Task:
    """An agent task of the evaluation."""

    name: str
    binding: str
    example: str | None
    """The example that the work folder starts with, or None for an empty folder."""
    gaps: tuple[str, ...]
    """The gaps that must be closed at the end, or ALL_GAPS."""
    check: Callable[[Path, Definition], list[str]]
    """The checks of the task: the problems of the work folder and of the definition."""
    files: dict[str, str] = field(default_factory=dict[str, str])
    """More files of the work folder before the run, by path. The app has its folder `app/`."""

    @property
    def prompt(self) -> str:
        text = (TASKS / f"{self.name}.md").read_text(encoding="utf-8")
        return " ".join(text.split())


TASK_LIST = [
    Task("new-definition", "fastapi", None, ALL_GAPS, check_new_definition),
    Task(
        "change-definition",
        "fastapi",
        "room-booking",
        ("operations.cancel_booking",),
        check_change_definition,
        {f"{APP}/app/features/bookings/cancel_booking_ext.py": CANCEL_BOOKING},
    ),
    Task(
        "fill-gaps",
        "nextjs",
        "project-tracker",
        ("operations.complete_task", "ui.dashboards.overview.widgets.workload"),
        check_fill_gaps,
    ),
    Task("seed-csv", "react", "room-booking", (), check_seed_csv, {"rooms.csv": ROOMS_CSV}),
]
TASK_BY_NAME = {task.name: task for task in TASK_LIST}


# The commands.


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return result.stdout.strip()


def appgen_version() -> str:
    return appgen("--version").stdout.split()[-1]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare(task: Task, folder: Path) -> str:
    """Make the folder of a run, and return the prompt of the task."""
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f"error: {folder} is not empty.")
    work = folder / "work"
    home = folder / "home"
    work.mkdir(parents=True)
    home.mkdir()
    if task.example:
        source = EXAMPLES / task.example
        # The definition and the files that it reads, without the hand-written code.
        shutil.copytree(
            source, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns("extensions")
        )
        result = appgen("generate", work / "app.yaml", "-b", task.binding, "-o", work / APP)
        if result.returncode != 0:
            raise SystemExit(f"error: appgen generate failed:\n{result.stderr}")
    for path, text in task.files.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text, encoding="utf-8")
    env = {**os.environ, "HOME": str(home)}
    result = subprocess.run(
        [sys.executable, "-m", "appgen", "skills", "install", "--scope", "user"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"error: appgen skills install failed:\n{result.stderr}")
    write_json(
        folder / "task.json",
        {
            "task": task.name,
            "binding": task.binding,
            "prompt": task.prompt,
            "appgen": appgen_version(),
            "commit": git_commit(),
            "prepared": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        },
    )
    return task.prompt


def task_of(folder: Path) -> Task:
    name = read_json(folder / "task.json").get("task")
    if name not in TASK_BY_NAME:
        raise SystemExit(f"error: {folder} has no task.json of a task. Run 'prepare' first.")
    return TASK_BY_NAME[name]


def run(folder: Path, model: str, claude: str, timeout: int) -> dict[str, Any]:
    """Run the agent on the task of a folder, and return the summary of the session."""
    task = task_of(folder)
    # In a session of Claude Code, the variables of the session would join
    # the run to it. Keep only the token of a cloud session.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("CLAUDE") or name in KEEP_VARIABLES
    }
    # The package caches of the real home folder, so that each run does
    # not download all packages again.
    env.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
    if shutil.which("pnpm"):
        store = subprocess.run(["pnpm", "store", "path"], capture_output=True, text=True)
        if store.returncode == 0:
            env.setdefault("npm_config_store_dir", store.stdout.strip())
    env["HOME"] = str(folder / "home")
    command = [
        claude,
        "-p",
        task.prompt,
        "--model",
        model,
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    started = datetime.datetime.now(datetime.UTC)
    with (folder / "log.jsonl").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=folder / "work",
            env=env,
            stdout=log,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    summary = session_summary(folder / "log.jsonl")
    summary.update(
        {
            "model": model,
            "started": started.isoformat(timespec="seconds"),
            "exit_code": result.returncode,
            "stderr": result.stderr[-2000:],
        }
    )
    write_json(folder / "run.json", summary)
    return summary


def session_summary(log: Path) -> dict[str, Any]:
    """Read the turns, the time, the cost, and the commands of a session log."""
    summary: dict[str, Any] = {"validate_runs": 0, "commands": []}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("type") == "system" and message.get("subtype") == "init":
            summary["session_model"] = message.get("model")
        if message.get("type") == "assistant":
            for part in message.get("message", {}).get("content", []):
                if part.get("type") == "tool_use" and part.get("name") == "Bash":
                    command = str(part.get("input", {}).get("command", ""))
                    summary["commands"].append(command)
                    summary["validate_runs"] += len(re.findall(r"\bappgen validate\b", command))
        if message.get("type") == "result":
            summary.update(
                {
                    "turns": message.get("num_turns"),
                    "duration_s": round((message.get("duration_ms") or 0) / 1000),
                    "cost_usd": message.get("total_cost_usd"),
                    "is_error": message.get("is_error"),
                    "result": message.get("result"),
                }
            )
    return summary


def app_tests(binding: str, app: Path, folder: Path) -> tuple[bool, str]:
    """Run the tests of a generated app. Return the result and the output of a failure.

    The tests of a FastAPI app use SQLite in the folder of the run, unless
    `TEST_DATABASE_URL` names another database.
    """
    if binding == "fastapi":
        commands = [["uv", "sync", "--quiet"], ["uv", "run", "pytest", "-q"]]
    else:
        commands = [["pnpm", "install"], ["pnpm", "lint"], ["pnpm", "typecheck"], ["pnpm", "build"]]
    # The app has its own environment, not the one of this script.
    env = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    env.setdefault("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{folder.resolve() / 'test.db'}")
    for command in commands:
        result = subprocess.run(
            command, cwd=app, env=env, capture_output=True, text=True, timeout=1800, check=False
        )
        if result.returncode != 0:
            output = (result.stdout + result.stderr)[-3000:]
            return False, f"'{' '.join(command)}' failed:\n{output}"
    return True, ""


def score(folder: Path, run_app_tests: bool) -> dict[str, Any]:
    """Score the work folder of a run, and write score.json."""
    task = task_of(folder)
    work = folder / "work"
    definition_file = work / "app.yaml"
    app = work / APP
    problems: list[str] = []
    checks: dict[str, bool | None] = {}

    validation = (
        appgen_json("validate", definition_file, "-f", "json")
        if definition_file.is_file()
        else None
    )
    checks["valid"] = bool(validation and validation["valid"])
    if not checks["valid"]:
        problems.append("the definition is missing or not valid")

    report = appgen_json("check", definition_file, app, "-f", "json") if app.is_dir() else None
    checks["no_invalid_traces"] = bool(report and not report["invalid"])
    if report is None:
        problems.append("appgen check did not run: no app, or a definition that is not valid")
    elif report["invalid"]:
        problems.append(f"appgen check reports {len(report['invalid'])} invalid traces")
    open_gaps = (
        sorted({g["id"] for g in [*report["gaps"], *report["gaps_to_close"]]}) if report else []
    )
    expected = open_gaps if task.gaps == ALL_GAPS else [g for g in task.gaps if g in open_gaps]
    checks["gaps_closed"] = report is not None and not expected
    if expected:
        problems.append(f"open gaps: {', '.join(expected)}")

    copy = folder / "regenerated"
    shutil.rmtree(copy, ignore_errors=True)
    written = None
    if app.is_dir() and checks["valid"]:
        shutil.copytree(app, copy)
        result = appgen("generate", definition_file, "-b", task.binding, "-o", copy)
        match = re.search(r"^Files written: (\d+)", result.stdout, re.MULTILINE)
        written = int(match.group(1)) if match else None
        checks["no_manual_edits"] = result.returncode == 0 and written == 0
        if result.returncode != 0:
            problems.append(f"appgen generate stops: {result.stderr.strip()[-500:]}")
        elif written != 0:
            problems.append(
                f"a new appgen generate writes {written} files: the app is not generated "
                "from the last definition"
            )
        shutil.rmtree(copy)
    else:
        checks["no_manual_edits"] = False

    if run_app_tests and app.is_dir():
        passed, output = app_tests(task.binding, app, folder)
        checks["app_tests"] = passed
        if not passed:
            problems.append(output)
    else:
        checks["app_tests"] = None

    data: object = None
    if definition_file.is_file():
        try:
            data = yaml.safe_load(definition_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            data = None
    task_problems = task.check(work, _mapping(data))
    checks["task"] = not task_problems
    problems += task_problems

    result = {
        "version": 1,
        "task": task.name,
        "binding": task.binding,
        "passed": all(value is not False for value in checks.values()),
        "checks": checks,
        "problems": problems,
        "open_gaps": open_gaps,
        "files_written_by_a_new_run": written,
        "scored": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    }
    write_json(folder / "score.json", result)
    return result


def report(folders: list[Path]) -> str:
    """Return a Markdown table of the runs of some folders."""
    marks = {True: "yes", False: "no", None: "-"}
    columns = [
        ("Run", "---"),
        ("Task", "----"),
        ("Model", "-----"),
        ("Turns", "----:"),
        ("Time (s)", "-------:"),
        ("Cost (USD)", "---------:"),
        ("`validate` runs", "--------------:"),
        *((title, "-" * len(title)) for title in CHECK_TITLES.values()),
        ("Passed", "------"),
    ]
    rows = [
        "| " + " | ".join(title for title, _ in columns) + " |",
        "| " + " | ".join(line for _, line in columns) + " |",
    ]
    for folder in folders:
        run_data = read_json(folder / "run.json")
        result = read_json(folder / "score.json")
        checks = result.get("checks", {})
        cost = run_data.get("cost_usd")
        cells = [
            folder.name,
            result.get("task", "?"),
            run_data.get("model", "-"),
            str(run_data.get("turns", "-")),
            str(run_data.get("duration_s", "-")),
            f"{cost:.2f}" if isinstance(cost, int | float) else "-",
            str(run_data.get("validate_runs", "-")),
            *(marks.get(checks.get(name)) for name in CHECK_TITLES),
            marks.get(result.get("passed")),
        ]
        rows.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(rows) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Make the folder of a run.")
    prepare_parser.add_argument("task", choices=sorted(TASK_BY_NAME))
    prepare_parser.add_argument("folder", type=Path)
    run_parser = commands.add_parser("run", help="Run the agent on the task of a folder.")
    run_parser.add_argument("folder", type=Path)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--claude", default="claude", help="The Claude Code command.")
    run_parser.add_argument("--timeout", type=int, default=1800, help="Seconds. Default: 1800.")
    score_parser = commands.add_parser("score", help="Score the folder of a run.")
    score_parser.add_argument("folder", type=Path)
    score_parser.add_argument("--no-app-tests", action="store_true")
    report_parser = commands.add_parser("report", help="Print a table of runs.")
    report_parser.add_argument("folders", type=Path, nargs="+")
    args = parser.parse_args(argv)

    if args.command == "prepare":
        print(prepare(TASK_BY_NAME[args.task], args.folder))
    elif args.command == "run":
        summary = run(args.folder, args.model, args.claude, args.timeout)
        print(json.dumps({k: v for k, v in summary.items() if k != "commands"}, indent=2))
    elif args.command == "score":
        result = score(args.folder, not args.no_app_tests)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["passed"] else 1
    else:
        print(report(args.folders), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
