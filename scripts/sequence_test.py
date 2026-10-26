"""Create records in a generated app, and check the numbers of their sequences.

The test generates nothing: it runs in the Next.js or the React app of
tests/fixtures/invoices.yaml.

- Next.js, with PGlite (in memory): apply the migrations of the app
  (`pnpm db:generate` makes them), and run the seed. Then create invoices
  and lines with the repositories of the app, as the server actions do.
  The rules of the input drop a value of the number.
- React, without an API: list the mock data, and create invoices and
  lines in the mock store.

The seed records and the generated records have the numbers of the
sequences in their order, from `start`, and each new record gets the
next number.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/sequence_test.py --app <folder> [--binding react]

scripts/check-nextjs.sh and scripts/check-react.sh run it. It needs
pnpm, but not Docker. The React test runs tsx with `pnpm dlx`.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from appgen.bindings.nextjs.versions import DEV_DEPENDENCIES

SCRIPT = ".appgen-sequence-test.ts"

_REPORT = """\
const report = {
  seeded: seeded.items.map((invoice: any) => invoice.number),
  created: [first.number, second.number],
  linePositions: lines.items.map((item: any) => item.position),
  newLine: line.position,
};
console.log(JSON.stringify(report));
process.exit(0);
"""

_NEXTJS = (
    """\
import { migrate } from "drizzle-orm/pglite/migrator";

import { customerRepository } from "./src/entities/customer/server";
import { invoiceInputSchema } from "./src/entities/invoice/model/schema";
import { invoiceRepository } from "./src/entities/invoice/server";
import { lineRepository } from "./src/entities/line/server";
import { getDb } from "./src/shared/db/client";
import { seedDatabase } from "./src/shared/db/seed";

const db: any = getDb();
await migrate(db, { migrationsFolder: "drizzle" });
await seedDatabase(db);

const sort = (field: string) => [{ field, direction: "asc" as const }];
const seeded = await invoiceRepository.list({ sort: sort("number") });
const customer = await customerRepository.create({ name: "Initech" });
const first = await invoiceRepository.create({ issuedOn: "2026-03-01", customerId: customer.id });
// The rules of the input, as in the server action, drop a number from the browser.
const input = invoiceInputSchema.parse({
  issuedOn: "2026-03-02",
  customerId: customer.id,
  number: "INV-0001",
});
const second = await invoiceRepository.create(input);
const lines = await lineRepository.list({ sort: sort("position") });
const line = await lineRepository.create({ text: "Support", invoiceId: first.id });
"""
    + _REPORT
)

_REACT = (
    """\
import { customerApi } from "./src/entities/customer/api/customer-api";
import { invoiceApi } from "./src/entities/invoice/api/invoice-api";
import { lineApi } from "./src/entities/line/api/line-api";

const sort = (field: string) => [{ field, direction: "asc" as const }];
const seeded = await invoiceApi.list({ sort: sort("number") });
const customer = await customerApi.create({ name: "Initech" });
const first = await invoiceApi.create({ issuedOn: "2026-03-01", customerId: customer.id });
// The mock store gives the number also when the input has one.
const second = await invoiceApi.create({
  issuedOn: "2026-03-02",
  customerId: customer.id,
  number: "INV-0001",
} as any);
const lines = await lineApi.list({ sort: sort("position") });
const line = await lineApi.create({ text: "Support", invoiceId: first.id });
"""
    + _REPORT
)

SEEDED = 6
"""The invoices of the seed: 2 seed records and 4 generated records."""
LINES = 12
"""The generated lines of the seed."""


def expected() -> dict[str, Any]:
    """Return the report of a correct app."""
    return {
        "seeded": [f"INV-{1001 + i}" for i in range(SEEDED)],
        "created": [f"INV-{1001 + SEEDED}", f"INV-{1002 + SEEDED}"],
        "linePositions": list(range(1, LINES + 1)),
        "newLine": LINES + 1,
    }


def _command(binding: str, app: Path) -> list[str]:
    if binding == "react":
        # The React app has no tsx. tsx reads the paths of tsconfig.json (`@/`).
        return ["pnpm", "--silent", "dlx", f"tsx@{DEV_DEPENDENCIES['tsx']}", SCRIPT]
    print("sequence-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    # The condition react-server lets the server modules (`server-only`) load in tsx.
    return ["pnpm", "--silent", "exec", "tsx", "--conditions=react-server", SCRIPT]


def run(app: Path, binding: str) -> None:
    command = _command(binding, app)
    script = app / SCRIPT
    script.write_text(_REACT if binding == "react" else _NEXTJS, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_")}
    env |= {"DATABASE_URL": "pglite:"}
    try:
        print(f"sequence-test: list and create invoices ({binding})", flush=True)
        result = subprocess.run(
            command, cwd=app, check=True, capture_output=True, text=True, env=env, timeout=300
        )
    except subprocess.CalledProcessError as error:
        sys.exit(f"sequence-test: the test failed:\n{error.stdout}\n{error.stderr}")
    finally:
        script.unlink(missing_ok=True)
    report = json.loads(str(result.stdout).strip().splitlines()[-1])
    want = expected()
    problems = [
        f"{key} is {report.get(key)}, expected {value}"
        for key, value in want.items()
        if report.get(key) != value
    ]
    for problem in problems:
        print(f"sequence-test: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print("sequence-test: passed (the numbers of the seed and of new records are in order)")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The generated app.")
    parser.add_argument("--binding", choices=("nextjs", "react"), default="nextjs")
    args = parser.parse_args()
    run(args.app, args.binding)


if __name__ == "__main__":
    main()
