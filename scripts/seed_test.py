"""Run the seed of a generated Next.js app two times, and check the records (ADR 0021).

The seed records of the definition go in by ID, and the generated records
only into empty tables. This test proves it with PGlite (in memory):

1. Apply the migrations of the app (`pnpm db:generate` makes them).
2. Run the seed. Each table must have the seed records and the generated
   records of the definition (`appgen.bindings.shared.mock_data`).
3. Change a field of one seed record, and delete another seed record
   that no record refers to.
4. Run the seed again. It must add only the deleted record, and keep
   the change. With `auth` and the sign-in with a password, each user
   must have a credential (`SEED_PASSWORD`).

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/seed_test.py <definition> --app <folder>

scripts/check-nextjs.sh runs it for tests/fixtures/seed-data.yaml. It
needs pnpm, but not Docker.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from appgen.bindings.nextjs.db import build_tables
from appgen.bindings.shared.mock_data import mock_data, seed_records
from appgen.dsl import AppDefinition, check_file
from appgen.gen.naming import camel

SCRIPT = ".appgen-seed-test.ts"
PASSWORD = "seed-test-password"
CHANGED = "Changed by the seed test"

_TEST = """\
import {{ eq }} from "drizzle-orm";
import {{ migrate }} from "drizzle-orm/pglite/migrator";

import {{ connect }} from "./src/shared/db/connect";
import * as schema from "./src/shared/db/schema";
import {{ seedDatabase }} from "./src/shared/db/seed";

const plan = {plan};
const tables: Record<string, any> = {{ {tables} }};
const db: any = connect("pglite:");
await migrate(db, {{ migrationsFolder: "drizzle" }});

async function counts(): Promise<Record<string, number>> {{
  const result: Record<string, number> = {{}};
  for (const [name, table] of Object.entries(tables)) {{
    result[name] = await db.$count(table);
  }}
  return result;
}}

const first = await seedDatabase(db);
const afterFirst = await counts();
const change = tables[plan.change.entity];
await db
  .update(change)
  .set({{ [plan.change.key]: plan.change.value }})
  .where(eq(change.id, plan.change.id));
if (plan.remove) {{
  const table = tables[plan.remove.entity];
  await db.delete(table).where(eq(table.id, plan.remove.id));
}}
const second = await seedDatabase(db);
const afterSecond = await counts();
const [changed] = await db.select().from(change).where(eq(change.id, plan.change.id));
const credentials = {credentials};
const report = {{ first, second, afterFirst, afterSecond, credentials }};
console.log(JSON.stringify({{ ...report, changed: changed[plan.change.key] }}));
process.exit(0);
"""


def plan(definition: AppDefinition) -> dict[str, Any]:
    """Return the record to change and the record to delete: seed records of the definition."""
    data = mock_data(definition)
    seeds = seed_records(definition)
    referred: set[str] = set()
    for records in data.values():
        for record in records:
            for name, value in record.items():
                items = cast(list[object], value) if isinstance(value, list) else [value]
                if name != "id":
                    referred.update(item for item in items if isinstance(item, str))
    change: dict[str, Any] | None = None
    remove: dict[str, Any] | None = None
    for entity_name, records in seeds.items():
        entity = definition.entities[entity_name]
        texts = [
            name
            for name, field in entity.stored_fields.items()
            if field.type in ("string", "text") and not field.unique and field.pattern is None
        ]
        for record in records:
            if change is None and texts:
                change = {"entity": entity_name, "id": record["id"], "key": camel(texts[0])}
                change["value"] = CHANGED[: entity.fields[texts[0]].max_length or len(CHANGED)]
            elif remove is None and record["id"] not in referred:
                remove = {"entity": entity_name, "id": record["id"]}
    if change is None:
        sys.exit("seed-test: the definition has no seed record with a text field to change.")
    return {"change": change, "remove": remove}


def run(definition_path: Path, app: Path) -> None:
    definition, diagnostics = check_file(definition_path)
    if definition is None or diagnostics:
        sys.exit(f"seed-test: the definition is not valid: {diagnostics}")
    steps = plan(definition)
    tables = build_tables(definition)
    auth = definition.auth
    credentials = (
        "await db.$count(schema.credentialsTable)" if auth is not None and auth.password else "null"
    )
    text = _TEST.format(
        plan=json.dumps(steps),
        tables=", ".join(f"{table.entity}: schema.{table.const}" for table in tables),
        credentials=credentials,
    )
    print("seed-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    script = app / SCRIPT
    script.write_text(text, encoding="utf-8")
    try:
        print("seed-test: run the seed two times with PGlite", flush=True)
        result = subprocess.run(
            ["pnpm", "--silent", "exec", "tsx", SCRIPT],
            cwd=app,
            check=True,
            capture_output=True,
            text=True,
            env={**_environment(), "SEED_PASSWORD": PASSWORD},
        )
    except subprocess.CalledProcessError as error:
        sys.exit(f"seed-test: the seed failed:\n{error.stdout}\n{error.stderr}")
    finally:
        script.unlink(missing_ok=True)
    report = json.loads(str(result.stdout).strip().splitlines()[-1])
    check(definition, steps, report)


def check(definition: AppDefinition, steps: dict[str, Any], report: dict[str, Any]) -> None:
    """Compare the report of the test with the records of the definition. Exit with 1 on a
    difference."""
    data = mock_data(definition)
    expected = {name: len(records) for name, records in data.items()}
    problems: list[str] = []
    if report["afterFirst"] != expected:
        problems.append(f"after the first run: {report['afterFirst']}, expected {expected}")
    if report["first"] != sum(expected.values()):
        problems.append(
            f"the first run added {report['first']} records, not {sum(expected.values())}"
        )
    removed = 1 if steps["remove"] else 0
    if report["second"] != removed:
        problems.append(f"the second run added {report['second']} records, not {removed}")
    if report["afterSecond"] != expected:
        problems.append(f"after the second run: {report['afterSecond']}, expected {expected}")
    if report["changed"] != steps["change"]["value"]:
        problems.append(f"the second run changed a record that exists: {report['changed']!r}")
    auth = definition.auth
    if auth is not None and auth.password:
        users = expected[auth.user_entity]
        if report["credentials"] != users:
            problems.append(f"{report['credentials']} credentials, expected {users}")
    for problem in problems:
        print(f"seed-test: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print(
        f"seed-test: passed ({sum(expected.values())} records; the second run added "
        f"{removed} deleted seed record and changed none)"
    )


def _environment() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("definition", type=Path)
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    args = parser.parse_args()
    run(args.definition, args.app)


if __name__ == "__main__":
    main()
