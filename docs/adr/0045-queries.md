# 0045. Custom queries that return a list

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

A custom operation acts on one record, and returns one record or
nothing. Some features of real apps read many records with logic that a
list endpoint does not have: the free time slots of a room, a ranked
feed, and the totals of each month of a financial statement. The rows of
such a feature are records of an entity, or rows with their own fields,
for example a month with a count and a sum.

The options for the logic:

- **More filters and groupings in the DSL.** Each feature needs its own
  keys, and a DSL of queries grows to SQL.
- **A custom operation that returns a list.** The operation acts on one
  record, and a query has no record.
- **A new kind of operation with params and a generation gap.** The
  extension file holds the logic, and the generated code gives the
  endpoint, the checks of the params, the page, and the access rules.

## Decision

An operation takes `kind: query`, with optional `params` and with one of
these keys:

- `returns: <Entity>`: each row is a record of the entity.
- `result`: a mapping of fields, for rows that are not records. The
  type of a field is a type that a view can show (`string`, `text`,
  `integer`, `decimal`, `boolean`, `date`, `datetime`, `uuid`, `email`,
  `url`, or `enum`). The keys of the entity fields that a row does not
  have (`unique`, `computed`, `translatable`, `filter`, `sequence`,
  `currency_field`, and `default`) are errors.

`entity` gives the slice of the query: the types and the files of the
query are in the slice of the entity. The params cannot have the names
`limit` and `offset`, because the page uses them.

The logic is a generation gap (ADR 0005). The function of the extension
file takes the params and returns **all** rows, in their order. The
generated code checks the params, applies the access rules, and returns
one page of the rows:

- FastAPI: `GET /<entity path>/<query name>`, with the params and
  `limit` and `offset` as query parameters, and the response `Page` of
  the list endpoints. The gap is `<query>_ext.py` in the slice of the
  entity, an async function of the session and the params. A row class
  `<Query>Row` holds the fields of `result`. The stub raises
  `NotImplementedError`, and the endpoint gives 501.
- Next.js: a server action `<query>Action(params, page)` and a function
  `<query>(params, page)` in `src/features/<query>`. The gap is a server
  module of the same folder.
- React with mock data: a function `<query>(params, page)` in
  `src/features/<query>`, with the gap next to it. With the FastAPI app
  (`x-react-data: api`), the function calls the endpoint, and has no
  gap.

The permission of the query applies as for the other operations. The
record rules of the roles for the entity of `returns` apply after the
gap: the generated code keeps only the records that the user may read.
So a hand-written query cannot show a record of another user by
mistake. The rows of `result` are not records, and the extension file
is responsible for them.

## Consequences

- An app can have the free slots, the feeds, and the statements of the
  report "appgen Real App Coverage" with hand-written logic and
  generated endpoints.
- The page of the rows is in memory: the gap returns all rows. A query
  over many records must limit its rows itself. A later change can give
  the page to the gap.
- The views of a query and the filters that give the params come in a
  later change. An `operation` action cannot run a query.
- The element kind `result_field` is new. Each binding covers it.
