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

### Views of a query

Added on 2026-10-27. A table, a card list, or a calendar takes
`query: <operation>` in place of `entity`, with separate model classes
(`QueryTableView`, `QueryCardsView`, `QueryCalendarView`), as the views
of API data (ADR 0022). The options for the params:

- **Only literal params.** A view of the free slots of a day cannot
  change the day.
- **The filters of the entity views** (`kind: search`, `select`, ...).
  These filters test the fields of the records, and a param is not a
  field.
- **A filter for each param.** The type of the param gives the input:
  a text, a number, a date, a date and time, a select of the values of
  an enum, or a switch for a boolean.

The view has the third option: `filters` names the params that the user
gives, and `params` gives the others, as a literal or as
`$route.<name>`, a path parameter of the page. Each param gets one
value, and each required param needs a value. While the filter of a
required param has no value, the view does not run the query.

The view loads one page of the rows with the function of the query, so
the same view works in each front end: in the Next.js app the server
action runs the gap on the server, and the React app calls the endpoint
of the FastAPI app, or the gap with mock data. The query gives the
order of the rows, so the view has no sort. The rows of `returns` are
records, and a view shows their fields and `id`, and links to the page
of a record. A view does not load the related records, so it does not
show the relations. A calendar loads all rows, one page of 200 rows at
a time.

## Consequences

- An app can have the free slots, the feeds, and the statements of the
  report "appgen Real App Coverage" with hand-written logic and
  generated endpoints.
- The page of the rows is in memory: the gap returns all rows. A query
  over many records must limit its rows itself. A later change can give
  the page to the gap.
- An `operation` action cannot run a query: a view shows its rows.
- A view of a query cannot show the related records of its rows. A
  query that needs them gives the values in the fields of `result`.
- The element kinds `query_table_view`, `query_cards_view`,
  `query_calendar_view`, `query_column`, `query_card`, and
  `query_filter` are new. The front ends cover them.
- The element kind `result_field` is new. Each binding covers it.
