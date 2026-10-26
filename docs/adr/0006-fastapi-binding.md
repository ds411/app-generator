# 0006. FastAPI binding

- Date: 2026-10-23
- Deciders: Maintainers

## Status

Accepted

## Context

The PoC generates three apps: one full-stack app (Next.js), one
front-end app (React), and one back-end app. The FastAPI binding writes
the back-end app: a standalone REST API in Python. It does not depend on
the front-end bindings.

The plan sets the stack: FastAPI 0.161 on Python 3.14, uv, a vertical
slice architecture, SQLAlchemy, Alembic, and Postgres, and a Dockerfile.
The binding must follow the trace format (ADR 0004) and the generation
gap mechanism (ADR 0005).

An app definition also has pages and a UI section (ADR 0002 and ADR
0003). A REST API has no screens, so these elements do not belong in its
code. Without a change to the binding contract, the generator makes a
gap file for each of them, and the trace checker reports them as open
gaps.

In a vertical slice architecture, the code of one feature is in one
place, from the endpoint to the data access. The usual alternative is a
layered app (`routers/`, `schemas/`, `models/`, `services/`), where one
feature has code in each layer.

## Decision

### Scope

The binding covers the app, the entities, the fields, the relations,
the operations, and the params. It declares `page` and `ui` in a new
field of the binding contract, `excludes`. The generator makes no gap
for an element of an excluded kind, or for the elements under it. The
manifest records the excluded kinds, and `appgen check` does not count
these elements in the coverage.

The binding reads the stat, chart, and list widgets of the dashboards
for their endpoints (M26, see [Dashboards](#dashboards)). The `ui`
kinds stay excluded: the traces of these endpoints do not count in the
coverage.

### Layout

Each entity is a vertical slice in `app/features/<slice>/`. The slice
name is the plural of the entity in snake case, for example `tasks`, or
the `plural_label` of the entity in snake case, for example `people`.
The slice name is also the table name and the URL prefix
(`/tasks`, `/people`). The extension keys `x-fastapi-table` and
`x-fastapi-path` of an entity change the table name and the URL prefix
(#186). The slice folder keeps its name.

| Path                               | Content                                         |
| ---------------------------------- | ----------------------------------------------- |
| `app/main.py`                      | `create_app()`: adds the router of each slice.  |
| `app/core/`                        | Code that all slices share: settings, database, errors, and pagination. |
| `app/features/<slice>/router.py`   | The router of the slice. It adds the router of each operation. |
| `app/features/<slice>/schemas.py`  | The Pydantic schemas of the entity.             |
| `app/features/<slice>/models.py`   | The SQLAlchemy model of the entity.             |
| `app/features/<slice>/repository.py` | The data access that the operations share.    |
| `app/features/<slice>/<operation>.py` | One module for each CRUD or list operation: its endpoint and its handler. |
| `app/features/<slice>/<operation>_gen.py` | The endpoint of a custom operation.      |
| `app/features/<slice>/<operation>_ext.py` | The logic of a custom operation (extension file). |
| `app/features/dashboards/<dashboard>.py` | The endpoints of the widgets of a dashboard. |
| `migrations/`                      | The Alembic migrations.                         |
| `Dockerfile`, `compose.yaml`       | The image of the API, and a stack with Postgres and the migrations. |
| `tests/`                           | The tests, with one module for each operation.  |

A slice imports from `app/core/`. Relations between entities are the
only imports from one slice to another: a model refers to the model of
its target, and a read schema can embed the read schema of its target.

### Names

Definition names are snake case, so the binding uses them for columns,
attributes, and JSON keys. A name that is a Python keyword, or that
hides a name of SQLAlchemy or Pydantic (for example `metadata`), gets a
final underscore as attribute name. The column and the JSON key keep
the definition name. If two names of an entity give the same Python
name (for example a field `owner_id` and a relation `owner`), the
generator stops with an error.

### Persistence

- SQLAlchemy 2 with async sessions (asyncpg), one session for each
  request.
- Each entity has a primary key `id` of type UUID.
- A `many_to_one` relation, and the owning side of a `one_to_one`
  relation, have a foreign key column `<relation>_id`. Of a pair of
  `one_to_one` relations, the side with `required` or `on_delete` owns
  the key. Else the side that comes first in the definition owns it.
  The extension key `x-fastapi-column` changes the column name. The
  attribute and the JSON key stay `<relation>_id`.
- A `many_to_many` relation has a join table `<slice>_<relation>`. A
  pair of inverse relations shares the table of the side that comes
  first in the definition. The extension key `x-fastapi-table` of one
  of the two sides changes the table name.
- Two tables, or two URL prefixes, with the same name stop the
  generator with an error.
- Enum fields are text columns with a check constraint, not native
  Postgres enums, so that a migration can add a value easily.
- One generated Alembic migration creates the schema of the current
  definition.

### REST API

| Kind     | Method | Path                    | Success |
| -------- | ------ | ----------------------- | ------- |
| `create` | POST   | `/<slice>`              | 201     |
| `read`   | GET    | `/<slice>/{id}`         | 200     |
| `update` | PATCH  | `/<slice>/{id}`         | 200     |
| `delete` | DELETE | `/<slice>/{id}`         | 204     |
| `list`   | GET    | `/<slice>`              | 200     |
| `custom` | POST   | `/<slice>/{id}/<name>`  | 200, or 204 if it returns `none` |

- A custom operation works on one record of its entity. Its params are
  the JSON body.
- A second operation of the same kind for one entity gets the path of
  the kind plus its name in kebab case, for example
  `GET /tasks/open-tasks`.
- List endpoints take `limit`, `offset`, `sort` (sort keys, a `-`
  before a key sorts in descending order), and one equality filter for
  each field that has a simple type. The views of the entity add
  parameters: a select filter makes the parameter of its field a
  list, a date range filter adds `<field>_from` and `<field>_to`, and
  the search filters add `q`, which searches all their fields with
  `ILIKE` (Postgres) or `LIKE` (SQLite). The sortable columns and the
  sort of the views add sort keys, also through relations, for example
  `owner` (the display field of the target) or `project.name`. A field
  path through relations uses `has()` in a filter, and a correlated
  subquery in a sort key. Computed fields and relations to many records
  have no sort key. Each list endpoint takes `id` (a list of IDs), for
  the related records of a page in the React client (M26), and `q` also
  searches the display field when it is a text. A board makes the
  parameter of its group field a list, and a calendar adds the date
  ranges of its start field and of a required end field. With
  `x-fastapi-search: fulltext` (M26), `q` is a web search with the
  full-text search of Postgres (`websearch_to_tsquery`), on a GIN index
  of the text fields of the entity, and the rank orders the records
  without a sort. On SQLite, `q` stays `LIKE`.
- All errors use the problem details format of RFC 9457
  (`application/problem+json`).
- Input schemas give a relation as the ID of the target (`project_id`),
  or a list of IDs for `many_to_many` (`member_ids`). Read schemas give
  the same IDs. A relation with the extension key `x-fastapi-embed: true`
  is also in the read schema as the object of the target.

### Dashboards

The slice `app/features/dashboards/` has one module for each dashboard,
and one endpoint for each stat, chart, and list widget:
`GET /dashboards/<dashboard>/<widget>` (#339). The operation ID is
`<dashboard>_<widget>`. A custom widget has no endpoint.

| Widget  | Response                                 | Query                                   |
| ------- | ---------------------------------------- | --------------------------------------- |
| `stat`  | `StatValue`: `{"value": 3.0}`            | The aggregate of the records of the filter. |
| `chart` | `ChartValues`: `{"groups": [{"key": "done", "value": 2.0}]}` | `GROUP BY` the group field, or the month of a date field, or the foreign key of a relation. |
| `list`  | A list of the read schema of the entity of the view | The filter, the sort, and the limit of the widget. |

- The filter has the semantics of the browser: `ne` and `not_in` keep
  the records without a value, and a comparison with an empty value is
  false. A date-time field compares by the day in UTC with a date or
  `$today`. A field path joins the related records, and a relation to
  many records uses `any()`.
- A widget with `$today` in its filter, or `$now` for a date field,
  takes the query parameter `today` (a date). Without it, the server
  uses the date in UTC. `$now` for a date-time field is the time of the
  server.
- `count` gives the number of records. `sum` gives 0 without records,
  and `avg`, `min`, and `max` give `null`.
- A widget needs the permission of the first list operation of its
  entity, and reads only the records of the record rule of the role
  ([ADR 0025](0025-record-rules.md)), with the filter of the list
  endpoints (`repository.owned`). A list widget hides the embedded
  records that the rules hide. A widget of an entity with a public list
  operation is public.
- A widget that reads a computed field (in its field, its filter, its
  group, or its sort) stops the generator with an error, because the
  database has no column for it.
- The generated tests check each widget without records, and with known
  records: three records pass the filter, and each next record fails
  one part of it. They run on Postgres and on SQLite. A filter with an
  empty value or a field path through relations has no value test.

### Generation gaps

- A custom operation has a generated endpoint in `<operation>_gen.py`,
  which calls a function with a fixed name in `<operation>_ext.py`.
  The stub raises `NotImplementedError`, and the API gives status 501
  with problem details for it.
- Each entity has an extension file `validation_ext.py` with a function
  that the create and update operations call before they store a
  record. By default, it accepts all records.
- An element of a kind that the binding does not cover gets a Markdown
  gap file in `gaps/`.

### Tests

The generated tests use pytest and httpx. They run against Postgres in
a container (Testcontainers), or against the database in the
`TEST_DATABASE_URL` variable. The tests need valid values for the
fields. The binding makes them from the field type and options. For a
`string` with a `pattern`, it makes strings from the pattern. If it
cannot, the app author gives a value with the extension key
`x-example`.

Each operation has a test module with the success case and the main
error cases: input that is not valid (422), a missing record (404), a
reference to a missing record (422), and a duplicate unique value
(409). Factories store the records for a test through the repository
of each slice, with the records that a required relation needs. The
generated tests of a custom operation check only its errors, because
the generator does not know its logic. One test calls the operation on
a stored record: while the stub raises `NotImplementedError`, the API
gives 501 with problem details, and after the developer writes the
logic, the test checks that the API gives no server error (#156).

## Consequences

- The code of a feature is in one folder, so a developer finds the
  endpoint, the schemas, and the data access of an entity together.
- The binding contract gets a new optional field, `excludes`. Other
  back-end bindings can use it, and front-end bindings can exclude
  kinds that they do not need.
- Relations make slices import from each other. The slices are not
  fully independent.
- One generated migration fits a new database, not a database with
  data. To change the schema of a database with data, the developer
  writes a new migration by hand, for example with
  `alembic revision --autogenerate`. [ADR 0009](0009-fastapi-schema-changes.md)
  makes this the documented flow: the generator creates the first
  migration once, and a new run keeps all migrations.
- The rules for the routes, the foreign keys, and the join tables are
  fixed. An app author cannot change them without a new extension key.
