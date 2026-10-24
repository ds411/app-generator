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

## Consequences

- The two generated apps work together without a change by hand.
- The React binding imports the model of the FastAPI binding: a change
  of the endpoints of the FastAPI app changes the client too.
- A list with many records loads slowly, because the client loads all
  its pages. Server filters for more operators, the search, and the
  sort would fix this. They need a change of the list endpoints.
- The custom operations run on the server, so their extension files of
  the React app are not generated in this mode.
