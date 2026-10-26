# 0039. A manual order with drag and drop

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

Before this decision, a table and a board sorted their records by a
field, or by the ID. A team that ranks its backlog, or the steps of a
plan, had no order of its own: a user could not put a record above
another record.

- A manual order must stay after a reload, and must be the same for all
  users. Thus it is a value of each record, in the database, and the
  apps change it with the update operation of the entity.
- The Next.js app and the React app without an API have all records of
  a view in the browser. The React app with `x-react-data: api` has one
  page of the records (M26).
- A move must change few records. A new position for each record after
  the moved record makes many requests for a long list.
- Two users can move records at the same time.

## Decision

We give a table and a board an optional `order_field`: an `integer`
field of the entity. The view sorts its records by this field, from the
smallest value, and a record without a value comes last. A view with
`order_field` has no `sort`. The field has no `unique`, no `max`, and a
`min` of 1 or less, is not computed, and has no sequence: the apps write
it with the update operation of the entity, which the entity must have.

A user moves a row of a table with its handle, by drag and drop or with
the arrow keys on the handle. A user moves a card of a board by drag
and drop, also to another column. The moved record gets a value between
the values of its two neighbors: the middle value, rounded down. At the
top of the list, the lower neighbor is 0. At the end, the value is the
value of the last record plus 1024. When no integer is free between the
neighbors, or a neighbor has no value, the app renumbers the list: the
records get 1024, 2048, 3072, and so on, in the new order, and the app
updates only the records whose value changes.

The list of a move is the list that the user sees: the filtered records
of a table, or the cards of the column of a board. A table that the user
sorts by a column does not show the handles. With the API client, the
app loads all records of the view (the parameters of the view and its
filters, sorted by the order field) for a move, so that a renumber
covers the records of the other pages too.

## Consequences

- An app author gets a ranked backlog with one key, and the three
  bindings store the same values.
- Most moves change one record with one request. A renumber changes
  many records, one request each, but only after about ten moves into
  the same gap.
- Two users who move records at the same time can give two records the
  same value. Their order then comes from the ID, and the next move into
  that place renumbers the list.
- The records that a filter hides keep their values: a move between two
  shown records can put the record between hidden records too. A
  renumber of a filtered table changes only the shown records, so the
  hidden records can move relative to them.
- A new record without a value comes last, until a user moves it.
- The mock data of the React app is in memory: a reload shows the order
  of the mock data again.
