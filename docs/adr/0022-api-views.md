# 0022. Views of API data

- Date: 2026-10-25
- Deciders: Maintainers

## Status

Accepted

## Context

ADR 0019 gives each app a typed client for the operations of a
third-party API. Only hand-written code calls the clients: a view shows
the records of one entity (ADR 0003), and no view shows the answer of an
API without hand-written code.

The constraints:

- The answer of an API is not a record. It has no ID, the app cannot
  change it, and it has the schema of the OpenAPI document, not the
  fields of an entity.
- The Next.js app has a server client for each API, which keeps the
  secret of the API on the server. The React app runs in the browser:
  it has a client only for an API without a secret, or for an API that
  the FastAPI app exposes (`expose`, ADR 0019).
- The shared view templates render the tables, the cards, and the
  detail views of both front ends. They load the data with
  `useResource`, and show the loading, the empty, and the error states.
- The trace check must find a trace for each element of the view
  (ADR 0004).

We looked at two ways to describe the views:

- **An entity for each API schema.** The generator could make an entity
  from an object schema, and the views would stay the same. But an
  entity has records with an ID, operations, and a table in the
  database. The answer has none of them.
- **A view with a source.** A view names an operation in place of an
  entity, and its columns and fields name the properties of the
  answer.

## Decision

### The DSL

- A table, a card list, or a detail view can have `source:
  apis.<api>.operations.<id>` in place of `entity`. `params` gives the
  value of each parameter of the operation: a literal, or
  `$route.<name>` for a path parameter of the page.
- The model has separate classes for these views (`ApiTableView`,
  `ApiCardsView`, `ApiDetailView`). The union of the views selects the
  class by `kind` and by the key `source`. The type checker then finds
  each place that reads the entity of a view.
- A table or a card list needs an answer that is a list of objects, or
  an object with a list of objects in the property that `items` names.
  A detail view needs an answer that is an object.
- The columns, the card, the header, and the sections name properties
  of an item, also nested properties with dots (`address.city`). A
  shown property must have a value that the view can show as text: a
  scalar, or a list of scalars.
- A view of API data can sort, search, and page the loaded items. It
  has no actions, no row actions, no bulk actions, no selection, no
  tabs, and only search filters: its items are not records.
- The validator reports an operation with a body, an unknown parameter,
  a missing required parameter, a literal that does not match the
  schema of its parameter, an answer that does not suit the view, and
  an unknown property, with the element ID of the view. A view of API
  data is the content of a page without an entity, and the path of the
  page has each `$route` parameter.

### The bindings

- The default display format of a property comes from its schema: a
  date, a date and time, an email address, a URL, a number, a boolean,
  an enum value as a badge, else text.
- The Next.js app calls the operation in the server component of the
  page, with the server client, at each request (`connection()`): it
  does not keep the answer. The page gives the answer, or the message
  of the error, to the view. An error of the API shows the error state
  of the view, not an error page, and the retry renders the page again
  on the server.
- The React app calls the operation in the browser, with the client of
  the API: with mock data, the client gives the example answer of the
  document. With `x-react-data: api`, the client of an exposed API
  calls the endpoints of the FastAPI app. A view of an API with a secret
  and without `expose` is a generation gap: an extension file with a
  stub of the view.
- The FastAPI app shows no views: it ignores the views of API data.

## Consequences

- An app shows third-party data without hand-written code, and the
  secret of an API stays on a server.
- The views of API data reuse the shared templates, the value
  components, and the states of the views of records. A new feature of
  the views of records (for example a filter kind) does not apply to
  the views of API data until a change adds it.
- The view keeps the order of the answer, unless it has `sort`. The
  rows of a table have their position as the key, so a change of the
  answer can show a row with the state of another row.
- A page of API data in the Next.js app waits for the API before it
  renders. A slow API makes a slow page, up to the time limit of the
  client.
- The answer of the API is not checked at run time: the view trusts the
  schema of the document, as the clients do (ADR 0019).
