"""Read the totals of the records of a generated Next.js app (ADR 0034).

The test generates nothing: it runs in the Next.js app of
tests/fixtures/totals.yaml, with PGlite (in memory):

1. Apply the migrations of the app (`pnpm db:generate` makes them).
2. Add an invoice without lines, an invoice with three lines, and a
   post with votes and tags, with the repositories of the app, as the
   server actions do.
3. Check the totals of the records that the repositories give: after a
   create, in a list, in a read, and after an update. Each function
   (`count`, `sum`, `avg`, `min`, `max`) of a `one_to_many` relation,
   the filter of a total, and a `many_to_many` relation give the values
   of the database. The count and the sum of no records are 0, and the
   other functions give null.
4. Write journal entries with their lines in one transaction, as the
   server action of an operation with lines does. The compare rules over
   the totals of the lines check them at the end of the transaction: a
   balanced entry stays, and an unbalanced entry or an entry over its
   debit limit gives the message of its rule and stores nothing. An
   update of an entry out of a transaction checks the rules too.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/totals_test.py --app <folder>

scripts/check-nextjs.sh runs it. It needs pnpm, but not Docker.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = ".appgen-totals-test.ts"

_TEST = """\
import { migrate } from "drizzle-orm/pglite/migrator";

import { invoiceRepository } from "./src/entities/invoice/server";
import { invoiceLineRepository } from "./src/entities/invoice-line/server";
import { journalEntryRepository } from "./src/entities/journal-entry/server";
import { journalLineRepository } from "./src/entities/journal-line/server";
import { postRepository } from "./src/entities/post/server";
import { tagRepository } from "./src/entities/tag/server";
import { voteRepository } from "./src/entities/vote/server";
import { writeLines } from "./src/shared/api/lines";
import { getDb, inTransaction } from "./src/shared/db/client";

const db: any = getDb();
await migrate(db, { migrationsFolder: "drizzle" });

const INVOICE = [
  "countLines",
  "sumLinesAmount",
  "avgLinesAmount",
  "minLinesAmount",
  "maxLinesAmount",
];
const POST = ["countVotes", "sumVotesValue", "upvotesCountVotes", "countTags", "sumTagsWeight"];

/** Return the values of the keys of a record. */
function totals(record: any, keys: string[]): unknown[] {
  return keys.map((key) => record[key]);
}

/**
 * Write a journal entry with a debit limit of 100 and its lines in one
 * transaction, as the server action does. Return "stored", or the message
 * of the error.
 */
async function journal(lines: [number, number][]): Promise<string> {
  const items = lines.map(([debit, credit]) => ({ account: "Cash", debit, credit }));
  try {
    await inTransaction(async () => {
      const entry = await journalEntryRepository.create({ memo: "Entry", debitLimit: 100 });
      await writeLines(journalLineRepository, "JournalLine", "entryId", entry.id, items, "lines");
    });
    return "stored";
  } catch (error) {
    return (error as Error).message;
  }
}

const empty = await invoiceRepository.create({ number: "A-1" });
const full = await invoiceRepository.create({ number: "A-2", discount: 5 });
for (const amount of [10.5, 20, 30.25]) {
  await invoiceLineRepository.create({ description: "Line", amount, invoiceId: full.id });
}
const red = await tagRepository.create({ name: "red", weight: 2 });
const blue = await tagRepository.create({ name: "blue", weight: 3 });
const post = await postRepository.create({ title: "Post", tags: [red.id] });
for (const value of [1, 1, -1, 0]) {
  await voteRepository.create({ value, postId: post.id });
}
const invoices = await invoiceRepository.list({ sort: [{ field: "number", direction: "asc" }] });
const balanced = await journal([[40, 0], [0, 25.5], [0, 14.5]]);
const unbalanced = await journal([[40, 0], [0, 30]]);
const overLimit = await journal([[150, 0], [0, 150]]);
const [entry] = (await journalEntryRepository.list({})).items as any[];
let lowered = "stored";
try {
  await journalEntryRepository.update(entry.id, { debitLimit: 10 });
} catch (error) {
  lowered = (error as Error).message;
}
const entries = await journalEntryRepository.list({});
const report = {
  created: totals(empty, INVOICE),
  list: invoices.items.map((invoice: any) => totals(invoice, INVOICE)),
  read: totals(await invoiceRepository.get(full.id), INVOICE),
  post: totals(await postRepository.get(post.id), POST),
  changed: totals(await postRepository.update(post.id, { tags: [red.id, blue.id] }), POST),
  journal: [balanced, unbalanced, overLimit, lowered, entries.total, entries.items[0]?.debitLimit],
};
console.log(JSON.stringify(report));
process.exit(0);
"""

_NO_LINES = [0, 0, None, None, None]
_THREE_LINES = [3, 60.75, 20.25, 10.5, 30.25]


def expected() -> dict[str, Any]:
    """Return the report of a correct app."""
    return {
        "created": _NO_LINES,
        "list": [_NO_LINES, _THREE_LINES],
        "read": _THREE_LINES,
        # Four votes with the sum 1, two of them above 0, and one tag of weight 2.
        "post": [4, 1, 2, 1, 2],
        # The update gives the second tag: the totals of the response have it.
        "changed": [4, 1, 2, 2, 5],
        # One entry stays, with its debit limit of 100.
        "journal": [
            "stored",
            "The debits and the credits must balance.",
            "The debits must stay within the debit limit.",
            "The debits must stay within the debit limit.",
            1,
            100,
        ],
    }


def check(report: dict[str, Any]) -> list[str]:
    """Return the differences between the report of the test and a correct app."""
    return [
        f"the totals of {name} are {report.get(name)}, expected {answer}"
        for name, answer in expected().items()
        if report.get(name) != answer
    ]


def run(app: Path) -> None:
    print("totals-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    script = app / SCRIPT
    script.write_text(_TEST, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_")}
    env |= {"DATABASE_URL": "pglite:"}
    try:
        print("totals-test: read the totals with PGlite", flush=True)
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
        sys.exit(f"totals-test: the test failed:\n{error.stdout}\n{error.stderr}")
    except subprocess.TimeoutExpired as error:
        sys.exit(f"totals-test: the test did not end in {error.timeout} s:\n{error.stderr}")
    finally:
        script.unlink(missing_ok=True)
    report = json.loads(str(result.stdout).strip().splitlines()[-1])
    problems = check(report)
    for problem in problems:
        print(f"totals-test: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print(
        "totals-test: passed (5 functions, a filter, a many_to_many relation, "
        "and 2 compare rules over totals)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    run(parser.parse_args().app)


if __name__ == "__main__":
    main()
