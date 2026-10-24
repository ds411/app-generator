# 0009. Schema changes of the FastAPI app

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

The FastAPI binding generates one Alembic migration,
`migrations/versions/0001_schema.py`, that creates the schema of the
current definition ([ADR 0006](0006-fastapi-binding.md)). The
generator wrote the file again on each run. After a change to the
definition, the file described the new schema, so a database with data
(made with the old file) and the migration history did not agree. The
app developer had to write the next migration by hand, from zero.

The options:

- **A generated migration from the difference of two runs.** The
  generator keeps the schema of the last run (for example in the
  manifest), compares it with the schema of the new run, and writes a
  new migration for the difference. The generator must know each kind
  of schema change (a new column, a renamed column, a new constraint,
  a changed type), and it cannot know a rename from the definition
  alone: a rename looks like a removed and a new element. The output
  depends on the history of the runs, not only on the definition.
- **The `alembic revision --autogenerate` flow.** The generator writes
  the models from the definition, as before. The app developer makes
  the next migration with Alembic, which compares the models with the
  database, and reviews it. Alembic knows the operations of each
  database, also batch mode for SQLite. It cannot know a rename either,
  but the developer sees the migration before it runs.

## Decision

We use the `alembic revision --autogenerate` flow.

- The generator creates `0001_schema.py` once, from the definition of
  the first run, as a file that it never changes or deletes (an output
  rule with `extension: true`, ADR 0005). A new run keeps all files in
  `migrations/versions/`.
- The first migration has only a manual trace to the app
  (`@trace:manual app file`): after the first run, it belongs to the
  app developer. The models carry the traces to the entities, fields,
  and relations, so an element that goes away from the definition makes
  no trace in a migration invalid.
- `migrations/env.py` uses the batch mode of Alembic on SQLite, so that
  a migration can change a table of the local database.
- The steps for a schema change are in the README of the generated app
  and in `docs/bindings.md`: change the definition, generate the app
  again, run `uv run alembic revision --autogenerate -m "<change>"`,
  review the new file, and run `uv run alembic upgrade head`.
- `scripts/check_schema_change.py` (in `scripts/check-fastapi.sh`)
  applies the first migration to a database with a record, generates
  the app again with a new field, makes and applies the next migration,
  and checks that the record stays.
- An output folder of an older run, where `0001_schema.py` is a
  generated file in the manifest, keeps the file: the generator does
  not delete a generated file that a rule now creates once.

## Consequences

- A database with data keeps its data after a change to the
  definition, and the migration history grows with the app.
- The same definition still gives the same output on a new folder. In a
  folder with an earlier run, the first migration keeps the schema of
  that run.
- The app developer makes and reviews each migration after the first.
  Alembic does not find all changes: for example a rename (it gives a
  drop and an add), a changed enum value (a check constraint), or a
  changed server default. The developer edits the migration for them.
- A test of the generated app (`tests/test_migrations.py`) checks that
  the migrations create the schema of the models. After a change to the
  definition, it fails until the developer adds the next migration.
