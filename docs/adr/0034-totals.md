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

The front-end bindings do not compute totals in this decision: they
stop with an error for a computed field with a total.

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
