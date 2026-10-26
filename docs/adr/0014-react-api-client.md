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

### Update for M26: large lists everywhere

The views, the forms, and the filters of the React app no longer load
all records of an entity (#336, #337, #338):

- Each list endpoint of the FastAPI app takes `id` (a list of IDs), and
  `q` searches the display field when it is a text (`string`, `text`,
  or `email`).
- A view loads the related records of its page by ID: one request for
  each target entity (`HttpStore.byIds`, at most 100 IDs in a request).
  The generator orders the entities in stages (`RELATED`), because a
  related record can give the IDs of other related records, for example
  the owner of the project of a task. `loadRelated` loads a stage at a
  time, and loads again while it finds new IDs, for a cycle of
  relations. A detail view loads the related records of its record in
  the same way. The store keeps the records that it loads, and a change
  of a record clears them.
- A relation field of a form, and a select filter of a relation, search
  their options on the server (`<entity>Options`, an `OptionSource`):
  the first 20 records in the order of the display field, and `q` for a
  text. A select or a radio widget of a relation is a search box in this
  mode. The labels of the selected records come from `byIds`.
- A board loads one page for each column, with the value of the column
  in the query parameter of its group field, and shows the counts of
  the server. "Show more" loads more cards of a column. A move loads the
  columns again.
- A calendar loads only the records of the shown days. The list endpoint
  takes the date range of the start field, and also of a required end
  field: a record that starts before the last day and ends after the
  first day is on the calendar. The query adds one day at each end,
  because the server compares dates in UTC.
- The check script counts the requests of the pages: no page loads all
  records, the table loads the owners of its page by ID, the owner field
  searches and saves a person that is not on the first page of options,
  the board loads one page for each column and moves a card, and a
  calendar of the tasks (which the script adds to the definition) loads
  the shown days.
- A dashboard computes its values on the server (#339, #340). The
  FastAPI app has one endpoint for each stat, chart, and list widget
  (ADR 0006), and the dashboard calls each endpoint once with
  `Promise.all`. A widget with `$today` in its filter sends the date of
  the browser (`today`), so that the server and the browser agree on the
  day. A list widget then loads its related records by ID. A chart of a
  relation gives the IDs of the groups, and the dashboard loads their
  records by ID for the labels. With mock data, the dashboard computes
  the values in the browser as before.
- The check script compares the stat tiles of the dashboard with the
  values of the API and with the totals of the list endpoints. It checks
  that the dashboard calls each widget endpoint once, and that no
  request loads all records.

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
  the dashboards still load all pages of their entities. (Fixed in M26:
  see the update.)
- A dashboard in API mode needs the FastAPI app of the same definition:
  each widget has its own endpoint, so a change of a widget changes the
  two apps.
- The custom operations run on the server, so their extension files of
  the React app are not generated in this mode.
