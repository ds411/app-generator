"""Prepare, run, and score the agent tasks of the evaluation of the skills.

`docs/evaluation-skills.md` gives the results. The prompts of each task
are in `docs/evaluation/skill-tasks/<task>.md`: a line `---` separates
the prompts of a task with more than one prompt. A run uses one folder:

- `work/`: the folder of the agent. It has the definition and the app
  that the task starts from, and nothing else. The tasks of the
  quick-start skill start from a folder without a definition.
- `home/`: an empty home folder with the installed skills
  (`appgen skills install --scope user`), so that the skills of appgen
  are the only skills of the agent.
- `task.json`, `log.jsonl` (the session), `run.json`, and `score.json`:
  the files of the evaluation, outside the folder of the agent.

Commands, from the root of the repository:

    uv run scripts/evaluate_skill.py prepare <task> <folder>
    uv run scripts/evaluate_skill.py run <folder> --model <model>
    uv run scripts/evaluate_skill.py score <folder> [--no-app-tests]
    uv run scripts/evaluate_skill.py report <folder>...

`prepare` makes the folder and prints the prompts. `run` starts Claude
Code in print mode in `work/`, with `home/` as the home folder, and writes
`log.jsonl` and `run.json` (the turns, the time, the cost, and the number
of `appgen validate` runs). It sends each further prompt of the task in
the same session (`--resume`). The agent runs the `appgen` of its PATH:
install the appgen of the checkout first, with `uv tool install --force .`.
The run keeps the package caches of uv and pnpm of the real home folder.
The runs cost money, so no test and no hook runs `run`.

`score` writes `score.json`: the definition is valid, `appgen check`
reports no invalid traces, the expected gaps are closed, a new
`appgen generate` into a copy of each app writes no file (no generated
file has manual edits, and the app is generated from the last
definition), the tests of each app pass, the defaults agree with the
task, and the checks of the task pass (for example, the renamed entity
exists). The defaults of a task of the quick-start skill are the
bindings in their folders, the keys of the definition, and the rows of
the record of the defaults at the top of `app.yaml`. `--no-app-tests`
skips the tests of the apps. `report` prints a Markdown table of runs.
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
    "defaults": "Defaults",
    "task": "Task checks",
}
"""The checks of score.json, with their titles in the report."""
KEEP_VARIABLES = {"CLAUDE_SESSION_INGRESS_TOKEN_FILE"}
"""The variables of a Claude Code cloud session that a run needs."""
RECORD_START = "# appgen-quickstart defaults:"
"""The first line of the record of the defaults at the top of `app.yaml` (ADR 0053)."""
RECORD_LINE = re.compile(r'# - (?P<row>[a-z_]+): (?P<choice>.+)\. Prompt: "(?P<words>[^"]+)"')
"""A line of the record: the row of the table of defaults, the choice, and the words."""
MANUAL_TRACE = re.compile(r"@trace:manual\s+([A-Za-z_][\w.-]*)")
SKIP_FOLDERS = {"node_modules", ".venv", ".next", "dist", ".appgen", "__pycache__", ".git"}
"""The folders of an app that hold no hand-written code."""

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


def manual_traces(app: Path) -> dict[str, list[str]]:
    """Return the elements of the `@trace:manual` traces of an app, with their files."""
    found: dict[str, list[str]] = {}
    if not app.is_dir():
        return found
    for path in sorted(app.rglob("*")):
        relative = path.relative_to(app)
        if not path.is_file() or SKIP_FOLDERS & set(relative.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError, OSError:
            continue
        for element in MANUAL_TRACE.findall(text):
            found.setdefault(element, []).append(relative.as_posix())
    return found


def check_quickstart(work: Path, definition: Definition) -> list[str]:
    return []


def check_change_bindings(work: Path, definition: Definition) -> list[str]:
    """The hand-written code of the first prompt (the app `nextjs`) stays, also in the new apps.

    The first prompt gives the logic of a custom operation, so the first
    app has hand-written code. The second prompt changes the bindings:
    the folder of the first app stays, and the new apps have the logic
    of each element again (ADR 0053).
    """
    first = manual_traces(work / "nextjs")
    if not (work / "nextjs").is_dir():
        return ["the folder of the first app (nextjs) is gone"]
    if not first:
        return ["the first app (nextjs) has no hand-written code"]
    new = {**manual_traces(work / "react"), **manual_traces(work / "fastapi")}
    return [
        f"the new apps have no hand-written code of {element} (nextjs: {', '.join(files)})"
        for element, files in sorted(first.items())
        if element not in new
    ]


@dataclass(frozen=True)
class Defaults:
    """The expected defaults of a task of the quick-start skill (ADR 0053)."""

    apps: dict[str, str]
    """The binding of each app folder."""
    keys: tuple[str, ...] = ()
    """The keys of the definition: `<path>` (it exists), `<path>: <value>`, or `!<path>` (it
    does not exist). `<>` in a path is any name, for example `auth.providers.<>.issuer`."""
    rows: tuple[str, ...] = ()
    """The rows of the record of the defaults, for example `binding` and `auth`."""
    kept: tuple[str, ...] = ()
    """More app folders that stay from an earlier prompt, and that the score skips."""


@dataclass(frozen=True)
class Task:
    """An agent task of the evaluation."""

    name: str
    binding: str | None
    """The binding of the app `app/`, or None for a task of the quick-start skill."""
    example: str | None
    """The example that the work folder starts with, or None for an empty folder."""
    gaps: tuple[str, ...]
    """The gaps that must be closed at the end, or ALL_GAPS."""
    check: Callable[[Path, Definition], list[str]]
    """The checks of the task: the problems of the work folder and of the definition."""
    files: dict[str, str] = field(default_factory=dict[str, str])
    """More files of the work folder before the run, by path. The app has its folder `app/`."""
    defaults: Defaults | None = None
    """The expected defaults of a task of the quick-start skill."""

    @property
    def prompts(self) -> list[str]:
        text = (TASKS / f"{self.name}.md").read_text(encoding="utf-8")
        parts = re.split(r"^---$", text, flags=re.MULTILINE)
        return [" ".join(part.split()) for part in parts if part.strip()]

    @property
    def apps(self) -> dict[str, str]:
        """Return the binding of each app folder that the score checks."""
        if self.defaults is not None:
            return self.defaults.apps
        assert self.binding is not None
        return {APP: self.binding}


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
    Task(
        "quickstart-tool-library",
        None,
        None,
        (),
        check_quickstart,
        defaults=Defaults(
            {"nextjs": "nextjs"},
            keys=("auth.user_entity", "!auth.providers", "!auth.password"),
            rows=("binding", "app", "auth"),
        ),
    ),
    Task(
        "quickstart-mobile-api",
        None,
        None,
        (),
        check_quickstart,
        defaults=Defaults({"fastapi": "fastapi"}, keys=("auth.user_entity",), rows=("binding",)),
    ),
    Task(
        "quickstart-change-bindings",
        None,
        None,
        (),
        check_change_bindings,
        defaults=Defaults(
            {"react": "react", "fastapi": "fastapi"},
            keys=("app.x-react-data: api",),
            rows=("binding",),
            kept=("nextjs",),
        ),
    ),
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


def prepare(task: Task, folder: Path) -> list[str]:
    """Make the folder of a run, and return the prompts of the task."""
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f"error: {folder} is not empty.")
    work = folder / "work"
    home = folder / "home"
    work.mkdir(parents=True)
    home.mkdir()
    if task.example:
        assert task.binding is not None
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
            "apps": task.apps,
            "prompts": task.prompts,
            "appgen": appgen_version(),
            "commit": git_commit(),
            "prepared": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        },
    )
    return task.prompts


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
    started = datetime.datetime.now(datetime.UTC)
    log_file = folder / "log.jsonl"
    log_file.write_text("", encoding="utf-8")
    exit_code = 0
    stderr = ""
    for prompt in task.prompts:
        # Each further prompt continues the session of the first prompt.
        session = session_id(log_file)
        command = [
            claude,
            "-p",
            prompt,
            *(["--resume", session] if session else []),
            "--model",
            model,
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        with log_file.open("a", encoding="utf-8") as log:
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
        exit_code = result.returncode
        stderr += result.stderr
        if exit_code != 0:
            break
    summary = session_summary(log_file)
    summary.update(
        {
            "model": model,
            "started": started.isoformat(timespec="seconds"),
            "exit_code": exit_code,
            "stderr": stderr[-2000:],
        }
    )
    write_json(folder / "run.json", summary)
    return summary


def log_messages(log: Path) -> list[dict[str, Any]]:
    """Return the JSON messages of a session log."""
    messages: list[dict[str, Any]] = []
    for line in log.read_text(encoding="utf-8").splitlines() if log.is_file() else []:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            messages.append(cast(dict[str, Any], message))
    return messages


def session_id(log: Path) -> str | None:
    """Return the ID of the last session of a log, or None for an empty log."""
    ids = [str(m["session_id"]) for m in log_messages(log) if m.get("session_id")]
    return ids[-1] if ids else None


def session_summary(log: Path) -> dict[str, Any]:
    """Read the turns, the time, the cost, and the commands of a session log.

    A log of a task with more than one prompt has a result for each
    prompt. The summary adds their turns, times, and costs. After
    `--resume`, `total_cost_usd` includes the cost of the earlier
    prompts, so the cost of a result is its `model_usage_since_last_result`.
    """
    summary: dict[str, Any] = {"validate_runs": 0, "commands": [], "results": []}
    for message in log_messages(log):
        if message.get("type") == "system" and message.get("subtype") == "init":
            summary["session_model"] = message.get("model")
        if message.get("type") == "assistant":
            for part in message.get("message", {}).get("content", []):
                if part.get("type") == "tool_use" and part.get("name") == "Bash":
                    command = str(part.get("input", {}).get("command", ""))
                    summary["commands"].append(command)
                    summary["validate_runs"] += len(re.findall(r"\bappgen validate\b", command))
        if message.get("type") == "result":
            summary["results"].append(message.get("result"))
            usage = _mapping(message.get("model_usage_since_last_result"))
            cost = (
                sum(_mapping(model).get("costUSD") or 0 for model in usage.values())
                if usage
                else message.get("total_cost_usd") or 0
            )
            summary.update(
                {
                    "turns": (summary.get("turns") or 0) + (message.get("num_turns") or 0),
                    "duration_s": (summary.get("duration_s") or 0)
                    + round((message.get("duration_ms") or 0) / 1000),
                    "cost_usd": (summary.get("cost_usd") or 0) + cost,
                    "is_error": bool(summary.get("is_error") or message.get("is_error")),
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
    apps = task.apps
    problems: list[str] = []
    checks: dict[str, bool | None] = {}

    def where(name: str) -> str:
        return f"{name}: " if len(apps) > 1 else ""

    validation = (
        appgen_json("validate", definition_file, "-f", "json")
        if definition_file.is_file()
        else None
    )
    checks["valid"] = bool(validation and validation["valid"])
    if not checks["valid"]:
        problems.append("the definition is missing or not valid")

    checks["no_invalid_traces"] = True
    open_gaps: set[str] = set()
    reports = 0
    for name in apps:
        app = work / name
        report = appgen_json("check", definition_file, app, "-f", "json") if app.is_dir() else None
        if report is None:
            checks["no_invalid_traces"] = False
            problems.append(
                f"{where(name)}appgen check did not run: no app, or a definition that is not valid"
            )
            continue
        reports += 1
        if report["invalid"]:
            checks["no_invalid_traces"] = False
            problems.append(
                f"{where(name)}appgen check reports {len(report['invalid'])} invalid traces"
            )
        open_gaps |= {g["id"] for g in [*report["gaps"], *report["gaps_to_close"]]}
    expected = (
        sorted(open_gaps) if task.gaps == ALL_GAPS else [g for g in task.gaps if g in open_gaps]
    )
    checks["gaps_closed"] = reports == len(apps) and not expected
    if expected:
        problems.append(f"open gaps: {', '.join(expected)}")

    written: int | None = None
    checks["no_manual_edits"] = bool(checks["valid"])
    for name, binding in apps.items():
        app = work / name
        if not (app.is_dir() and checks["valid"]):
            checks["no_manual_edits"] = False
            continue
        copy = folder / "regenerated"
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(app, copy, ignore=shutil.ignore_patterns(*SKIP_FOLDERS - {".appgen"}))
        result = appgen("generate", definition_file, "-b", binding, "-o", copy)
        shutil.rmtree(copy)
        match = re.search(r"^Files written: (\d+)", result.stdout, re.MULTILINE)
        count = int(match.group(1)) if match else None
        written = None if count is None else (written or 0) + count
        if result.returncode != 0:
            checks["no_manual_edits"] = False
            problems.append(f"{where(name)}appgen generate stops: {result.stderr.strip()[-500:]}")
        elif count != 0:
            checks["no_manual_edits"] = False
            problems.append(
                f"{where(name)}a new appgen generate writes {count} files: the app is not "
                "generated from the last definition"
            )

    checks["app_tests"] = None
    if run_app_tests:
        checks["app_tests"] = True
        for name, binding in apps.items():
            if not (work / name).is_dir():
                checks["app_tests"] = False
                continue
            passed, output = app_tests(binding, work / name, folder)
            if not passed:
                checks["app_tests"] = False
                problems.append(f"{where(name)}{output}")

    text = definition_file.read_text(encoding="utf-8") if definition_file.is_file() else ""
    data: object = None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        data = None
    checks["defaults"] = None
    if task.defaults is not None:
        default_problems = defaults_problems(work, task.defaults, text, _mapping(data))
        checks["defaults"] = not default_problems
        problems += default_problems
    task_problems = task.check(work, _mapping(data))
    checks["task"] = not task_problems
    problems += task_problems

    result = {
        "version": 1,
        "task": task.name,
        "binding": task.binding,
        "apps": apps,
        "passed": all(value is not False for value in checks.values()),
        "checks": checks,
        "problems": problems,
        "open_gaps": sorted(open_gaps),
        "files_written_by_a_new_run": written,
        "scored": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    }
    write_json(folder / "score.json", result)
    return result


def record_rows(text: str) -> tuple[list[str], list[str]]:
    """Return the rows of the record of the defaults at the top of a definition, and the problems.

    The record starts with RECORD_START, and has a line in the format of
    RECORD_LINE for each default (the skill appgen-quickstart).
    """
    lines = text.splitlines()
    if RECORD_START not in lines:
        return [], [f"app.yaml has no record of the defaults: no line '{RECORD_START}'"]
    rows: list[str] = []
    problems: list[str] = []
    for line in lines[lines.index(RECORD_START) + 1 :]:
        if not line.startswith("# - "):
            break
        match = RECORD_LINE.fullmatch(line.rstrip())
        if match is None:
            problems.append(f"a line of the record does not have the format of the skill: {line}")
        else:
            rows.append(match.group("row"))
    return rows, problems


def _values(data: object, path: list[str]) -> list[object]:
    """Return the values at a path of keys. `<>` is any key of a mapping."""
    if not path:
        return [data]
    mapping = _mapping(data)
    head, rest = path[0], path[1:]
    keys = list(mapping) if head == "<>" else [head] if head in mapping else []
    return [value for key in keys for value in _values(mapping[key], rest)]


def key_problem(data: Definition, spec: str) -> str | None:
    """Check a key of the expected defaults: `<path>`, `<path>: <value>`, or `!<path>`."""
    path, separator, text = spec.removeprefix("!").partition(": ")
    values = _values(data, path.split("."))
    if spec.startswith("!"):
        return f"the definition has {path}" if values else None
    if not values:
        return f"the definition has no {path}"
    expected: object = yaml.safe_load(text)
    if separator and expected not in values:
        return f"the definition has {path}: {', '.join(map(str, values))}, not {text}"
    return None


def defaults_problems(work: Path, defaults: Defaults, text: str, data: Definition) -> list[str]:
    """Compare the bindings, the definition, and the record with the expected defaults."""
    problems: list[str] = []
    for name, binding in defaults.apps.items():
        found = read_json(work / name / ".appgen" / "manifest.json").get("binding")
        if found != binding:
            problems.append(f"the folder {name} has no app of the binding {binding}")
    others = sorted(
        manifest.parent.parent.relative_to(work).as_posix()
        for manifest in work.glob("**/.appgen/manifest.json")
        if not SKIP_FOLDERS & set(manifest.parent.parent.relative_to(work).parts)
    )
    for name in others:
        if name not in defaults.apps and name not in defaults.kept:
            problems.append(f"the folder {name} has an app that the task does not expect")
    problems += [p for spec in defaults.keys if (p := key_problem(data, spec))]
    rows, record_problems = record_rows(text)
    problems += record_problems
    missing = [row for row in defaults.rows if row not in rows]
    if missing:
        problems.append(f"the record of the defaults has no row {', '.join(missing)}")
    return problems


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
        print("\n".join(prepare(TASK_BY_NAME[args.task], args.folder)))
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
