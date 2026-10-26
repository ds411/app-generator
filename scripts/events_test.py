"""Change the records of a generated Next.js app, and check the runs of their events (ADR 0031).

The test generates nothing: it runs in the Next.js app of
tests/fixtures/events.yaml, with the hand-written operations of
tests/fixtures/events-extensions/nextjs/, and with PGlite (in memory):

1. Apply the migrations of the app (`pnpm db:generate` makes them).
2. Create, change, and delete tasks with the repository of the app, as
   the server actions do. The operation of each event writes an entry
   of the log, and fails for some values.
3. Check the result of each step, the tasks, and the entries: each event
   runs its operation after the change, in the transaction of the
   change, and the repository gives the record as the operation leaves
   it. A failed operation rolls back the change and the writes of the
   operation. A change in the operation of an event starts no event, a
   change of a field that `changed` does not watch runs no operation,
   and the operation of `deleted` gets the deleted record.

PGlite has one connection: a query outside the transaction of the change
waits for its end. So a test that ends in time also shows that the
operations write in the transaction of the change.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/events_test.py --app <folder>

scripts/check-nextjs.sh runs it. It needs pnpm, but not Docker.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = ".appgen-events-test.ts"

_TEST = """\
import { migrate } from "drizzle-orm/pglite/migrator";

import { entryRepository } from "./src/entities/entry/server";
import { taskRepository } from "./src/entities/task/server";
import { getDb } from "./src/shared/db/client";

const db: any = getDb();
await migrate(db, { migrationsFolder: "drizzle" });

/** Return the result of a step: the task, or the message of the error. */
async function step(work: () => Promise<any>): Promise<unknown> {
  try {
    const task = await work();
    if (task === undefined) {
      return "done";
    }
    return { title: task.title, points: task.points, score: task.score, status: task.status };
  } catch (error) {
    return { error: (error as Error).message };
  }
}

const steps: Record<string, unknown> = {};
const first = await taskRepository.create({ title: "First" });
steps.created = await step(async () => taskRepository.get(first.id));
steps.createdResult = await step(async () => first);
steps.failedCreate = await step(() => taskRepository.create({ title: "FAIL new" }));
steps.points = await step(() => taskRepository.update(first.id, { points: 5 }));
steps.title = await step(() => taskRepository.update(first.id, { title: "First task" }));
steps.failedPoints = await step(() => taskRepository.update(first.id, { points: 13 }));
steps.finish = await step(() => taskRepository.update(first.id, { status: "done" }));
steps.reopen = await step(() => taskRepository.update(first.id, { status: "open" }));
const stuck = await taskRepository.create({ title: "STUCK task" });
steps.failedFinish = await step(() => taskRepository.update(stuck.id, { status: "done" }));
const kept = await taskRepository.create({ title: "KEEP task" });
steps.failedDelete = await step(() => taskRepository.remove(kept.id));
steps.delete = await step(() => taskRepository.remove(first.id));
const tasks = await taskRepository.list({ sort: [{ field: "title", direction: "asc" }] });
const entries = await entryRepository.list();
const report = {
  steps,
  tasks: tasks.items.map((task: any) => ({
    title: task.title,
    points: task.points,
    status: task.status,
  })),
  entries: entries.items.map((entry: any) => entry.text).sort(),
};
console.log(JSON.stringify(report));
process.exit(0);
"""


def _task(title: str, points: int, score: int | None, status: str = "open") -> dict[str, Any]:
    return {"title": title, "points": points, "score": score, "status": status}


def expected() -> dict[str, Any]:
    """Return the report of a correct app."""
    return {
        "steps": {
            # The operation of `created` gives the task 1 point. That change
            # is in the operation of an event, so `recount` does not run.
            "created": _task("First", 1, None),
            # The repository gives the record as the operation leaves it.
            "createdResult": _task("First", 1, None),
            "failedCreate": {"error": "The test fails the create of FAIL new."},
            "points": _task("First", 5, 10),
            # A change of the title runs no `recount`.
            "title": _task("First task", 5, 10),
            "failedPoints": {"error": "The test fails the score of First task."},
            "finish": _task("First task", 5, 10, "done"),
            # The transition `reopen` has no operation.
            "reopen": _task("First task", 5, 10),
            "failedFinish": {"error": "The test fails the transition of STUCK task."},
            "failedDelete": {"error": "The test fails the delete of KEEP task."},
            "delete": "done",
        },
        # The failed create, change, transition, and delete roll back.
        "tasks": [
            {"title": "KEEP task", "points": 1, "status": "open"},
            {"title": "STUCK task", "points": 1, "status": "open"},
        ],
        # The failed operations roll back their entries too.
        "entries": sorted(
            [
                "created First",
                "recount First 5",
                "finished First task done",
                "created STUCK task",
                "created KEEP task",
                "deleted First task gone",
            ]
        ),
    }


def check(report: dict[str, Any]) -> list[str]:
    """Return the differences between the report of the test and a correct app."""
    problems: list[str] = []
    want = expected()
    for name, answer in want["steps"].items():
        if report["steps"].get(name) != answer:
            problems.append(f"the step {name} gave {report['steps'].get(name)}, expected {answer}")
    for key in ("tasks", "entries"):
        if report[key] != want[key]:
            problems.append(f"the {key} are {report[key]}, expected {want[key]}")
    return problems


def run(app: Path) -> None:
    print("events-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    script = app / SCRIPT
    script.write_text(_TEST, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_")}
    env |= {"DATABASE_URL": "pglite:"}
    try:
        print("events-test: change the tasks with PGlite", flush=True)
        # The condition react-server lets the server modules (`server-only`) load in tsx.
        result = subprocess.run(
            ["pnpm", "--silent", "exec", "tsx", "--conditions=react-server", SCRIPT],
            cwd=app,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            # A query outside the transaction of a change waits for it with PGlite: stop then.
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        sys.exit(f"events-test: the test failed:\n{error.stdout}\n{error.stderr}")
    except subprocess.TimeoutExpired as error:
        sys.exit(f"events-test: the test did not end in {error.timeout} s:\n{error.stderr}")
    finally:
        script.unlink(missing_ok=True)
    report = json.loads(str(result.stdout).strip().splitlines()[-1])
    problems = check(report)
    for problem in problems:
        print(f"events-test: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print("events-test: passed (4 kinds of events, 4 failed operations, and the stop of a loop)")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    run(parser.parse_args().app)


if __name__ == "__main__":
    main()
