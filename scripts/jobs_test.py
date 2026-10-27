"""Call the routes of the jobs of a generated Next.js app with a fixed clock (ADR 0029).

The test generates nothing: it runs in the Next.js app of
tests/fixtures/jobs.yaml, with the hand-written operations of
tests/fixtures/jobs-extensions/nextjs/, and with PGlite (in memory):

1. Apply the migrations of the app (`pnpm db:generate` makes them), and
   add customers and invoices.
2. Call the route handlers of the jobs (`POST /api/jobs/<job>`) with the
   parameter `now`: without the secret (401), without JOBS_FIXED_CLOCK
   (400), and then with the secret at the times of the runs.
3. Check the answers, the status of the invoices after each call, the
   rows of the table `job_runs`, and the log of the failed run: a job at
   a date field with an offset runs each record of its filter one time, a
   failed run rolls back and runs again at the next call, two calls at the
   same time run each run one time, and a job without an entity runs its
   extension function once for the time of its schedule.
4. Call the built-in job `stat_snapshots` (ADR 0042) on three days, and
   check the rows of the table `stat_snapshots` and the values that the
   server action of the chart of snapshots gives.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/jobs_test.py --app <folder>

scripts/check-nextjs.sh runs it. It needs pnpm, but not Docker.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = ".appgen-jobs-test.ts"
SECRET = "jobs-test-secret"

_TEST = """\
import { migrate } from "drizzle-orm/pglite/migrator";

import { getDb } from "./src/shared/db/client";
import * as schema from "./src/shared/db/schema";

const db: any = getDb();
await migrate(db, { migrationsFolder: "drizzle" });
const [vip, plain] = await db
  .insert(schema.customerTable)
  .values([
    { name: "VIP", vip: true },
    { name: "Plain", vip: false },
  ])
  .returning();
const invoice = (number: string, values: Record<string, unknown>) => ({
  number,
  dueOn: "2026-07-01",
  amount: 100,
  paid: false,
  status: "draft",
  customerId: plain.id,
  ...values,
});
const invoices = await db
  .insert(schema.invoiceTable)
  .values([
    invoice("D1", { dueOn: "2026-06-12" }),
    invoice("D2", { dueOn: "2026-06-12", paid: true, status: "paid" }),
    invoice("D3", { dueOn: "2026-06-11" }),
    invoice("D4", { dueOn: "2026-06-12", amount: 0 }),
    invoice("FAIL-1", { dueOn: "2026-06-12", amount: 50 }),
    invoice("F1", { sentAt: new Date("2026-06-15T09:30:00Z"), customerId: vip.id }),
    invoice("F2", { sentAt: new Date("2026-06-15T09:30:00Z") }),
    invoice("F3", { sentAt: new Date("2026-06-15T08:00:00Z"), customerId: vip.id }),
  ])
  .returning();
const numbers = new Map<string, string>(invoices.map((row: any) => [row.id, row.number]));

async function call(job: string, now: string, authorization: string | null): Promise<unknown> {
  const { POST } = await import(`./app/api/jobs/${job}/route`);
  const headers: Record<string, string> = authorization ? { authorization } : {};
  const url = `http://localhost/api/jobs/${job}?now=${now}`;
  const response: Response = await POST(new Request(url, { method: "POST", headers }));
  return { status: response.status, body: await response.json() };
}

async function statuses(): Promise<Record<string, string>> {
  const rows = await db.select().from(schema.invoiceTable);
  return Object.fromEntries(rows.map((row: any) => [row.number, row.status]));
}

const bearer = "Bearer " + process.env.JOBS_SECRET;
const steps: Record<string, unknown> = {};
// The daily snapshots of the stats on three days, before the other jobs change the invoices.
steps.snapshots = [];
for (const day of ["2026-06-11", "2026-06-12", "2026-06-13"]) {
  (steps.snapshots as unknown[]).push(await call("stat_snapshots", `${day}T00:05:00Z`, bearer));
}
steps.snapshotsAgain = await call("stat_snapshots", "2026-06-13T00:06:00Z", bearer);
const { billingOverduePerDayAction } = await import("./src/shared/api/snapshot-actions");
steps.chart = await billingOverduePerDayAction("2026-06-13");
steps.noSecret = await call("dunning", "2026-06-15T00:30:00Z", null);
steps.wrongSecret = await call("dunning", "2026-06-15T00:30:00Z", "Bearer wrong");
delete process.env.JOBS_FIXED_CLOCK;
steps.noFixedClock = await call("dunning", "2026-06-15T00:30:00Z", bearer);
process.env.JOBS_FIXED_CLOCK = "true";
const withStatuses = async (answer: unknown) => ({
  ...(answer as object),
  statuses: await statuses(),
});
steps.dunning = await withStatuses(await call("dunning", "2026-06-15T00:30:00Z", bearer));
steps.dunningAgain = await call("dunning", "2026-06-15T00:30:00Z", bearer);
steps.followUp = await withStatuses(await call("follow_up", "2026-06-15T12:00:00Z", bearer));
steps.overdueTwice = await Promise.all([
  call("overdue", "2026-06-15T07:00:00Z", bearer),
  call("overdue", "2026-06-15T07:00:00Z", bearer),
]);
steps.overdueStatuses = await statuses();
steps.overdueLater = await call("overdue", "2026-06-15T12:00:00Z", bearer);
steps.monthlyClose = await call("monthly_close", "2026-07-01T00:10:00Z", bearer);
steps.monthlyCloseAgain = await call("monthly_close", "2026-07-01T00:10:00Z", bearer);
const runs = await db.select().from(schema.jobRunsTable);
const customers = await db.select().from(schema.customerTable);
const snapshots = await db.select().from(schema.statSnapshotsTable);
const report = {
  steps,
  snapshots: snapshots.map((row: any) => [row.dashboard, row.widget, row.day, row.value]),
  failedId: invoices.find((row: any) => row.number === "FAIL-1").id,
  runs: runs
    .map((row: any) => ({
      key: row.recordId ? row.key.replace(row.recordId, numbers.get(row.recordId)) : row.key,
      status: row.status,
      attempts: row.attempts,
      error: row.error,
    }))
    .sort((a: any, b: any) => a.key.localeCompare(b.key)),
  customers: customers.map((row: any) => row.name).sort(),
};
console.log(JSON.stringify(report));
process.exit(0);
"""

_ANSWERS = {
    "noSecret": {"status": 401, "body": {"error": "Unauthorized"}},
    "wrongSecret": {"status": 401, "body": {"error": "Unauthorized"}},
    "noFixedClock": {
        "status": 400,
        "body": {"error": "The parameter now needs the setting JOBS_FIXED_CLOCK=true."},
    },
}


def _result(job: str, now: str, runs: int, failed: int = 0) -> dict[str, Any]:
    body = {"job": job, "now": now, "runs": runs, "failed": failed}
    return {"status": 500 if failed else 200, "body": body}


def _statuses(**changed: str) -> dict[str, str]:
    found = dict.fromkeys(("D1", "D3", "D4", "FAIL-1", "F1", "F2", "F3"), "draft") | {"D2": "paid"}
    return found | changed


_SNAPSHOT_DAYS = ("2026-06-11", "2026-06-12", "2026-06-13")
_OVERDUE = (0, 100, 250)
"""The overdue amount on each day: the unpaid invoices with a due date before the day."""


def expected() -> dict[str, Any]:
    """Return the report of a correct app, without the ID of the invoice FAIL-1."""
    dunning = "2026-06-15T00:30:00.000Z"
    close = "2026-07-01T00:10:00.000Z"
    # The status of FAIL-1 stays `draft`: its run rolls back.
    after_dunning = _statuses(D1="sent")
    runs: list[dict[str, Any]] = [
        {"key": "dunning:D1:2026-06-15T00:00:00Z", "status": "done", "attempts": 1},
        {"key": "dunning:FAIL-1:2026-06-15T00:00:00Z", "status": "failed", "attempts": 2},
        {"key": "follow_up:F1:2026-06-15T11:30:00Z", "status": "done", "attempts": 1},
        {"key": "monthly_close:-:2026-07-01T00:00:00Z", "status": "done", "attempts": 1},
        *(
            {"key": f"overdue:{number}:2026-06-15T06:30:00Z", "status": "done", "attempts": 1}
            for number in ("D1", "D3", "D4", "FAIL-1")
        ),
        *(
            {"key": f"stat_snapshots:-:{day}T00:00:00Z", "status": "done", "attempts": 1}
            for day in _SNAPSHOT_DAYS
        ),
    ]
    for run in runs:
        run["error"] = (
            "Error: The test fails the dunning letter 1 of FAIL-1."
            if run["status"] == "failed"
            else None
        )
    return {
        "steps": _ANSWERS
        | {
            "dunning": _result("dunning", dunning, 1, 1) | {"statuses": after_dunning},
            "dunningAgain": _result("dunning", dunning, 0, 1),
            "followUp": _result("follow_up", "2026-06-15T12:00:00.000Z", 1)
            | {"statuses": after_dunning | {"F1": "sent"}},
            "overdueStatuses": after_dunning
            | dict.fromkeys(("D1", "D3", "D4", "FAIL-1"), "paid")
            | {"F1": "sent"},
            "overdueLater": _result("overdue", "2026-06-15T12:00:00.000Z", 0),
            "monthlyClose": _result("monthly_close", close, 1),
            "monthlyCloseAgain": _result("monthly_close", close, 0),
            "snapshots": [
                _result("stat_snapshots", f"{day}T00:05:00.000Z", 1) for day in _SNAPSHOT_DAYS
            ],
            "snapshotsAgain": _result("stat_snapshots", "2026-06-13T00:06:00.000Z", 0),
            # The chart shows the last 2 days.
            "chart": {
                "ok": True,
                "data": [
                    {"key": day, "value": value}
                    for day, value in zip(_SNAPSHOT_DAYS[1:], _OVERDUE[1:], strict=True)
                ],
            },
        },
        # The open invoices: all but D2, which is paid.
        "snapshots": sorted(
            [
                *(
                    ["billing", "overdue_amount", day, value]
                    for day, value in zip(_SNAPSHOT_DAYS, _OVERDUE, strict=True)
                ),
                *(["billing", "open_invoices", day, 7] for day in _SNAPSHOT_DAYS),
            ],
            key=json.dumps,
        ),
        "runs": sorted(runs, key=lambda run: run["key"]),
        "customers": sorted(["Close 2026-07-01T00:00:00.000Z", "Plain", "VIP"]),
    }


def check(report: dict[str, Any], log: str) -> list[str]:
    """Return the differences between the report of the test and a correct app."""
    problems: list[str] = []
    steps = report["steps"]
    twice = steps.pop("overdueTwice")
    want = expected()
    # Two calls at the same time: together they run each of the 4 runs one time.
    counts = sorted(answer["body"]["runs"] for answer in twice)
    if sum(counts) != 4 or any(answer["status"] != 200 for answer in twice):
        problems.append(f"the two calls of overdue at the same time gave {twice}, not 4 runs")
    for name, answer in want["steps"].items():
        if steps.get(name) != answer:
            problems.append(f"the step {name} gave {steps.get(name)}, expected {answer}")
    if report["runs"] != want["runs"]:
        problems.append(f"the table job_runs has {report['runs']}, expected {want['runs']}")
    if report["customers"] != want["customers"]:
        problems.append(f"the customers are {report['customers']}, expected {want['customers']}")
    snapshots = sorted(report["snapshots"], key=json.dumps)
    if snapshots != want["snapshots"]:
        problems.append(f"the table stat_snapshots has {snapshots}, expected {want['snapshots']}")
    logged = [
        entry
        for entry in (json.loads(line) for line in log.splitlines() if line.startswith("{"))
        if entry.get("job") == "dunning"
    ]
    failed = {"record_id": report["failedId"], "due": "2026-06-15T00:00:00.000Z"}
    if len(logged) != 2 or any({k: e.get(k) for k in failed} != failed for e in logged):
        problems.append(f"the log has {logged}, not 2 entries of the failed run {failed}")
    return problems


def run(app: Path) -> None:
    print("jobs-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    script = app / SCRIPT
    script.write_text(_TEST, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_", "JOBS_"))}
    env |= {"DATABASE_URL": "pglite:", "JOBS_SECRET": SECRET, "JOBS_FIXED_CLOCK": "true"}
    try:
        print("jobs-test: call the routes of the jobs with a fixed clock and PGlite", flush=True)
        # The condition react-server lets the server modules (`server-only`) load in tsx.
        result = subprocess.run(
            ["pnpm", "--silent", "exec", "tsx", "--conditions=react-server", SCRIPT],
            cwd=app,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            # A query outside the transaction of a run waits for it with PGlite: stop then.
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        sys.exit(f"jobs-test: the test failed:\n{error.stdout}\n{error.stderr}")
    except subprocess.TimeoutExpired as error:
        sys.exit(f"jobs-test: the test did not end in {error.timeout} s:\n{error.stderr}")
    finally:
        script.unlink(missing_ok=True)
    report = json.loads(str(result.stdout).strip().splitlines()[-1])
    problems = check(report, str(result.stderr))
    for problem in problems:
        print(f"jobs-test: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print(
        "jobs-test: passed (4 jobs and the snapshots of 2 stats, 11 runs, a failed run, "
        "and 2 calls at the same time)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    run(parser.parse_args().app)


if __name__ == "__main__":
    main()
