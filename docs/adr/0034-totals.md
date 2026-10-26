# 0034. Totals of the relations in computed fields

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

Many apps show a value that comes from the related records of a record:
the total of the lines of an invoice, the number of votes of a post, or
the sum of the debits of a journal entry. A computed field could only
use the fields of its record and of the records of `many_to_one`
relations. The app developers had to add a stored field and change it
with each change of a related record, or add custom code to each view.

A total must be correct in each read and in each list, and the lists
must sort and filter by it. A list can have many records, so the apps
must not read the related records of each record one by one.

The options for the place of the computation:

- **A stored field that the apps change.** The read is fast. But each
  create, update, and delete of a related record must change the total,
  also a change that a script or a migration makes, and a missed change
  gives a wrong value that stays.
- **A database view or a trigger.** It is correct for each change. But
  each database has its own language, and the migrations must keep the
  view or the trigger.
- **Load the related records in the app, and compute in Python.** It is
  simple. But a list must load all related records of all records of
  the page, and the list cannot sort or filter by the total in the
  database.
- **A correlated subquery in each query of the records.** The database
  computes the total of each record in the same query. A sort and a
  filter use the same expression. The cost is one subquery for each
  total in each query of the entity.

## Decision

An expression of a computed field can use the functions `count`, `sum`,
`avg`, `min`, and `max` over a `one_to_many` or a `many_to_many`
relation of the entity: `count(lines)` or `sum(lines.amount)`. The
field of a total is a stored `integer` or `decimal` field of the
related entity, one step away. A total is a number in the expression,
for example `sum(lines.amount) - discount`. The new key `filter` of a
computed field selects the related records of all totals of its
expression, with the syntax of the filters of the dashboards, but
without `$today` and `$now`, so that a total does not change with the
time.

The total of no records is 0 for `count` and `sum`, and empty for
`avg`, `min`, and `max`.

The FastAPI binding computes each total in the database. Each distinct
total of an entity is a SQLAlchemy `column_property` of the model: a
correlated scalar subquery (`app/core/totals.py`). `app/models.py`
adds the column properties after it imports all models, because the
subquery uses the model of the related entity. The model declares the
attributes under `if TYPE_CHECKING:`, and the property of the computed
field reads them. Two fields with the same total and no filter share
one attribute. A relation of an entity to itself uses an alias of the
model.

When the expression of a computed field has only totals, numbers,
stored number fields of the entity, `+`, `-`, `*`, and `-` of one
operand, the list of the entity can sort by the field, and filter it
with the parameters `<field>_min` and `<field>_max`. An expression with
`/`, `hours`, `days`, or a field of a related record stays out of the
sort and the filters, because the database and Python round and divide
in different ways.

The front ends give the same values:

- A record of the Next.js app and of the React app with mock data has
  a key for each distinct total, with the name of the attribute of the
  FastAPI model in camel case, for example `sumLinesAmount`. The views
  compute the field from the keys, as from the other values of the
  record.
- The repository of the Next.js app reads the totals of its records in
  one more query, with a correlated subquery for each total (`total` in
  `src/shared/db/repository.ts`). The query names the table of the
  records `record`, so that the subquery of a relation of an entity to
  itself tells the record from its related records. Each list, read,
  create, and update of the repository gives the totals.
- The mock store of the React app computes each total from the records
  of the store of the related entity. A change of the related records
  notifies the views of the records with the totals.
- The React app with the FastAPI app (`x-react-data: api`) reads the
  value of each computed field with totals from the API.

### Compare rules over totals

A side (`field` or `other`) of a compare rule of an entity can be a
total of a `one_to_many` relation, for example `sum(lines.debit)` equal
to `sum(lines.credit)` for a journal entry. The rule is a check of the
record and its lines, so it runs after the lines are in the database:

- The FastAPI repository has `check_totals`: it flushes the changes,
  reads the totals of the rules again (`session.refresh`), and checks
  the rules. `create` and `update` of the repository call it, and an
  operation with lines calls it after it writes the lines, before the
  commit. A total that only the rules use is a deferred column
  property, so the queries of the entity do not read it.
- The Next.js repository has the options `totalRules` and `ruleTotals`
  (the subqueries of the totals that only the rules use). After a create
  or an update, it reads the row of the record with the totals, and
  checks the rules. In the work of `inTransaction()`, for example the
  server action of an operation with lines, the check runs at the end
  of the work (`checkAtEnd` in `src/shared/db/client.ts`), after the
  lines. A broken rule gives a ValidationError and rolls back the work.
- The React app with mock data does not check the rules of the
  entities. With the FastAPI app, the form shows the error of the API.
- The validator checks the rules with the seed records of the lines.
- The generated FastAPI tests give the fields of the rules fixed
  samples that keep the rules with no lines and with one to three lines,
  and send two lines that keep the rules and two lines that break each
  rule.

A change of a line through the operations of its own entity does not
check the rules of its record. A check there would break each journal
entry with its first line, before the second line exists. The record
and its lines change together in an operation with lines (ADR 0035).

## Consequences

- A total is correct after each change of the related records, also a
  change that a script makes, without more code or migrations.
- Each read and each list of an entity with totals has one subquery
  for each total. A large app can need an index on the foreign key of
  the relation (the `many_to_one` side has one).
- `create` and `update` of the repository read the record again after
  the commit (`populate_existing`), so the response of a create or an
  update has the totals. A custom operation that changes the related
  records must read the record again to get the new totals.
- The modules of the lists of an entity with totals import the models
  from `app.models`, so that the column properties exist when the
  module makes its sort keys.
- The filter of a total cannot use the time, a related record, or a
  computed field. A total of a total is not possible.
- The views of the Next.js app and of the React app with mock data sort
  and filter the computed fields with totals in the browser, as the
  other computed fields.
- A compare rule over totals costs one more query after each create and
  update of its entity. The operations of the lines can break the rule,
  and the mock data does not keep it.
