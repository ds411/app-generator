# 0007. Local database without a Postgres server

- Date: 2026-10-23
- Deciders: Maintainers

## Status

Accepted

## Context

The Next.js app (Drizzle) and the FastAPI app (SQLAlchemy and Alembic)
use Postgres. Docker Compose starts Postgres for the Docker runs. For a
run on the machine, the developer must start a Postgres server first.
The developer wants to try a generated app with only its own tools:
Node.js and pnpm, or uv.

The options:

- **SQLite.** It is a file, and Python includes it. Drizzle supports
  SQLite only with a second schema (`sqlite-core`, not `pg-core`) and
  a second set of migrations. The Next.js binding would generate two
  schemas, and the app would keep two migration folders.
- **PGlite.** A Postgres build in WebAssembly, as an npm package
  (`@electric-sql/pglite`). Drizzle has a PGlite driver and a PGlite
  migrator. The schema and the SQL migrations stay the same. PGlite
  runs in one process, and only one process can open its data folder.
  Python has no PGlite driver without Node.js.
- **An embedded Postgres server for Python** (for example the wheels
  that include the Postgres binaries). They depend on the platform, and
  they do not always support the newest Python version.

SQLAlchemy and Alembic support SQLite well. The FastAPI app needs only
small changes for SQLite: SQLite has no JSONB type, cannot add a
foreign key to a table, does not check foreign keys by default, and
keeps no time zone for a date and time.

## Decision

- Postgres stays the default database of both apps, and the only
  database of the Docker images and the Compose files.
- The **Next.js app uses PGlite** for local runs. A `DATABASE_URL` that
  starts with `pglite:` selects PGlite and its data folder, for example
  `pglite:./.pglite`. The app selects the Drizzle driver and the
  migrator from the URL. The schema and the migrations do not change.
- The **FastAPI app uses SQLite** with the `aiosqlite` driver for local
  runs, for example `DATABASE_URL=sqlite+aiosqlite:///./local.db`. The
  generated code works on both databases:
  - JSON fields use `JSON` with a `JSONB` variant for Postgres.
  - Date-time fields use a type that stores UTC on SQLite, and reads
    the values back with the UTC time zone.
  - The engine turns on the foreign key check of each SQLite
    connection.
  - The first migration adds the foreign keys in the batch mode of
    Alembic. On SQLite, Alembic copies the table.
  - The generated tests run on Postgres or on SQLite
    (`TEST_DATABASE_URL`).
- The check scripts run the generated FastAPI tests on SQLite, and
  start both apps with their local database (`scripts/smoke_test.py
  --local`).

## Consequences

- A developer can run the Next.js app with only Node.js and pnpm, and
  the FastAPI app with only uv.
- The Next.js app gets one more runtime package (`@electric-sql/pglite`,
  about 26 MB in `node_modules`). PGlite is slower than a Postgres
  server, and one process at a time can use its data.
- The FastAPI app gets one more runtime package (`aiosqlite`). SQLite
  is not Postgres: a hand-written query or a migration that uses a
  Postgres feature can fail on SQLite. The tests on SQLite in the check
  script find such a problem in the generated code, but not in the
  extension files.
- The FastAPI binding generates small types (`JSON_TYPE`, `Timestamp`)
  in `app/core/db.py`. The models use them instead of the SQLAlchemy
  types.
