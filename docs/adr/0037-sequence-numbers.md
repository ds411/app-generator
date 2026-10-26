# 0037. Sequence numbers of the fields

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

An invoice, an order, or a ticket has a number in order, for example
`INV-1001`. Before this decision, a field had a fixed default, and an
app author wrote code to give the next number.

- Two creates at the same time can read the same largest number. A
  database sequence (`CREATE SEQUENCE`, `nextval`) gives each create its
  own number, also when two creates run at the same time. PostgreSQL has
  sequences. SQLite has no sequences.
- A database sequence does not go back: a transaction that fails after
  `nextval` skips that number. A number without holes needs a lock of a
  counter row until the transaction ends.
- The FastAPI app runs its tests and the local development on SQLite,
  and the production on PostgreSQL. The Next.js app uses PostgreSQL, and
  PGlite in its tests. The React app without an API has mock data and an
  in-memory mock store.
- The seed records (ADR 0021) of the apps go into the database, and into
  the mock data of the React app.

## Decision

- A `string` or an `integer` field takes `sequence` with `start` (from
  1, default 1). A `string` field also takes `prefix` and `width`: the
  value is the prefix and the number with zeros before it, for example
  `INV-` and 4 give `INV-0042`. The validator rejects `sequence` with
  `required`, `default`, `computed`, `translatable`, and the rules of a
  value, a seed value of the field, a form field with the field, and a
  parameter with `sequence`.
- The records always have a value. The create and the change inputs do
  not have the field, and the default forms leave it out.
- The Next.js app declares a `pgSequence` for each field with
  `sequence`, and the column default is `nextval`. A string gets the
  prefix and the digits of `to_char` in SQL.
- The FastAPI app declares a SQLAlchemy `Sequence`, and the column
  default is an SQL expression with one compile rule for each dialect:
  `nextval` on PostgreSQL, and the largest number of the table plus one
  on SQLite. The mapper fetches the value after the insert
  (`eager_defaults`). The migration `0001` creates the sequences on
  PostgreSQL. The seed inserts the records of a table with a sequence one
  by one, so that SQLite gives each record its own number.
- The React mock data gives the numbers in order: first the seed
  records, then the generated records. The mock store gives a new record
  the largest number plus one.
- We accept the holes of a database sequence and do not lock a counter
  row. The docs say this.

## Consequences

- An app author gets numbers in order with one key, and the database
  gives them also when two creates run at the same time.
- A failed create skips a number on PostgreSQL. An app that needs a
  number without holes (for example because of a law about invoices)
  needs its own code.
- On SQLite, two creates at the same time can get the same number.
  `unique: true` on the field makes the second create fail. SQLite is
  for the tests and the local development only.
- A change of `start` after the first migration does not change the
  sequence in the database: the app author writes a migration
  (`ALTER SEQUENCE ... RESTART`).
- tests/fixtures/invoices.yaml has the fields with `sequence`. The check
  scripts generate and check its three apps, and
  scripts/sequence_test.py creates invoices in the Next.js app with
  PGlite.
