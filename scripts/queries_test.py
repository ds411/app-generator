"""Run the queries of a generated Next.js app, and check their pages of rows (ADR 0045).

The test generates nothing: it runs in the Next.js app of
tests/fixtures/listings.yaml, with the hand-written queries of
tests/fixtures/listings/extensions/nextjs/, and with PGlite (in memory):

1. Apply the migrations of the app (`pnpm db:generate` makes them).
2. Add listings and bookings with the repositories of the app, as the
   server actions do.
3. Call the generated server actions of the queries, as a page does,
   and check their results: the server action of `listings_for_guests`
   gives the listings of the extension file one page at a time, with the
   count of all rows. The server action of `bookings_by_month` gives the
   rows of `result`. A param or a page that is not valid gives a
   validation error, and the extension file does not run.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/queries_test.py --app <folder>

scripts/check-nextjs.sh runs it. It needs pnpm, but not Docker.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = ".appgen-queries-test.ts"

_TEST = """\
import { migrate } from "drizzle-orm/pglite/migrator";

import { bookingRepository } from "./src/entities/booking/server";
import { listingRepository } from "./src/entities/listing/server";
import { bookingsByMonthAction } from "./src/features/bookings-by-month/api/bookings-by-month.gen";
import {
  listingsForGuestsAction as listingsAction,
} from "./src/features/listings-for-guests/api/listings-for-guests.gen";
import { getDb } from "./src/shared/db/client";

const db: any = getDb();
await migrate(db, { migrationsFolder: "drizzle" });

const listings = [
  { title: "Harbour loft", city: "Lisbon", guests: 2, nightlyRate: 95 },
  { title: "Old town flat", city: "Lisbon", guests: 4, nightlyRate: 120 },
  { title: "River house", city: "Lisbon", guests: 6, nightlyRate: 180 },
  { title: "Canal room", city: "Amsterdam", guests: 2, nightlyRate: 110 },
];
const ids: Record<string, string> = {};
for (const listing of listings) {
  ids[listing.title] = (await listingRepository.create(listing)).id;
}
const bookings = [
  { guest: "Ana", checkIn: "2026-03-02", checkOut: "2026-03-06", listingId: ids["Harbour loft"] },
  { guest: "Ben", checkIn: "2026-03-10", checkOut: "2026-03-12", listingId: ids["Old town flat"] },
  { guest: "Chloe", checkIn: "2026-04-01", checkOut: "2026-04-08", listingId: ids["River house"] },
  { guest: "Dan", checkIn: "2027-01-05", checkOut: "2027-01-06", listingId: ids["Canal room"] },
];
for (const booking of bookings) {
  await bookingRepository.create(booking);
}

/** Return the titles of a page of listings and the counts, or the name of the error. */
function titles(result: any): unknown {
  if (!result.ok) return result.error.name;
  const { items, total, page, pageSize } = result.data;
  return { titles: items.map((item: any) => item.title), total, page, pageSize };
}

/** Return a page of the query listings_for_guests, from 1. */
async function listingsPage(params: any, page: number, pageSize = 50): Promise<unknown> {
  return titles(await listingsAction(params, { page, pageSize }));
}

const report: Record<string, unknown> = {
  first: await listingsPage({ city: "Lisbon", guests: 3 }, 1, 1),
  second: await listingsPage({ city: "Lisbon", guests: 3 }, 2, 1),
  all: await listingsPage({ city: "Lisbon" }, 1),
  none: await listingsPage({ city: "Porto" }, 1),
  badParam: await listingsPage({ city: "Lisbon", guests: 0 }, 1),
  badPage: await listingsPage({ city: "Lisbon" }, 0),
};
const months = await bookingsByMonthAction({ year: 2026 }, { page: 1, pageSize: 50 });
report.months = months.ok ? months.data : months.error.name;
console.log(JSON.stringify(report));
"""


def expected() -> dict[str, Any]:
    """Return the report of a correct app."""

    def page(titles: list[str], total: int, page: int, page_size: int) -> dict[str, Any]:
        return {"titles": titles, "total": total, "page": page, "pageSize": page_size}

    return {
        "first": page(["Old town flat"], 2, 1, 1),
        "second": page(["River house"], 2, 2, 1),
        "all": page(["Harbour loft", "Old town flat", "River house"], 3, 1, 50),
        "none": page([], 0, 1, 50),
        "badParam": "ValidationError",
        "badPage": "ValidationError",
        "months": {
            "items": [
                {"month": "2026-03-01", "bookings": 2, "nights": 6},
                {"month": "2026-04-01", "bookings": 1, "nights": 7},
            ],
            "total": 2,
            "page": 1,
            "pageSize": 50,
        },
    }


def check(report: dict[str, Any]) -> list[str]:
    """Return the differences between the report of the test and a correct app."""
    return [
        f"{name} is {report.get(name)}, expected {answer}"
        for name, answer in expected().items()
        if report.get(name) != answer
    ]


def run(app: Path) -> None:
    print("queries-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    script = app / SCRIPT
    script.write_text(_TEST, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_")}
    env |= {"DATABASE_URL": "pglite:"}
    try:
        print("queries-test: run the queries with PGlite", flush=True)
        # The condition react-server lets the server modules (`server-only`) load in tsx.
        result = subprocess.run(
            ["pnpm", "--silent", "exec", "tsx", "--conditions=react-server", SCRIPT],
            cwd=app,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        sys.exit(f"queries-test: the test failed:\n{error.stdout}\n{error.stderr}")
    except subprocess.TimeoutExpired as error:
        sys.exit(f"queries-test: the test did not end in {error.timeout} s:\n{error.stderr}")
    finally:
        script.unlink(missing_ok=True)
    report = json.loads(str(result.stdout).strip().splitlines()[-1])
    problems = check(report)
    for problem in problems:
        print(f"queries-test: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print("queries-test: passed (the pages of 2 queries, and 2 errors of the params and the page)")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    run(parser.parse_args().app)


if __name__ == "__main__":
    main()
