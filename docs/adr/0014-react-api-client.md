# 0014. API client of the React app

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

The React app has only mock data, by design for the PoC. The FastAPI
app of the same definition has a REST API and an OpenAPI document, but
the two apps cannot work together.

A client generator for OpenAPI (for example `openapi-typescript`) needs
the OpenAPI document when the React app is generated. The document
exists only when the FastAPI app runs, with its packages installed. The
model of the FastAPI binding, which makes that document, is available
in the generator.

## Decision

- The extension key `x-react-data` of the `app` section selects the data
  of the React app: `mock` (the default) or `api`.
- With `api`, the binding generates an HTTP client in `src/shared/api/`:
  `HttpStore` implements the interface `EntityApi` of the mock store, so
  the pages, views, and forms do not change.
- The paths, the methods, and the JSON names of the client come from the
  model of the FastAPI binding (`python_app`), the same source as the
  OpenAPI document of the API. A check script starts both apps, and
  checks each endpoint of the client in the OpenAPI document of the
  running API.
- The list endpoints filter only by equality. The client sends those
  filters to the API, loads all pages of a list, and applies the other
  filters, the search, the order, and the pages of the UI in the
  browser (`applyQuery`, the same code as the mock store).

### Update for M18: the query of a view on the server

The list endpoints of the FastAPI app now take the filters, the search
(`q`), and the sort keys of the views (#275). The client uses them:

- A table or a card list sends its filters, its search, its sort, and
  its page to the list endpoint with `HttpStore.page`, and loads one
  page. The names of the parameters and of the sort keys come from the
  query model of the FastAPI binding (`ListEndpoint`), the same source
  as the OpenAPI document. A column without a sort key on the server
  cannot sort.
- A tab of a detail view sends the foreign key of the inverse relation,
  or `id` for a `many_to_many` relation: the FastAPI binding adds `id`
  (a list of IDs) to the list endpoint of the target of such a tab. An
  empty list matches no records, without a request.
- `HttpStore.list` sends the filters `eq` and `in` and the sort of the
  keys that the endpoint takes, and throws an error for others. Without
  a page, it loads all pages. `applyQuery` runs only with mock data.
- A table keeps the last page on the screen until the next page loads,
  so that the filters keep their focus.
- The check script adds more projects than one page, and checks one
  request to the list endpoint for each page, the search, the sort, and
  the tabs of a project.

## Consequences

- The two generated apps work together without a change by hand.
- The React binding imports the model of the FastAPI binding: a change
  of the endpoints of the FastAPI app changes the client too.
- A list with many records loads slowly, because the client loads all
  its pages. Server filters for more operators, the search, and the
  sort would fix this. They need a change of the list endpoints.
  (Fixed in M18 for the tables and the card lists: see the update.)
- After the update for M18, the related records that a view shows (for
  example the people of the owner column), the boards, the forms, and
  the dashboards still load all pages of their entities.
- The custom operations run on the server, so their extension files of
  the React app are not generated in this mode.
