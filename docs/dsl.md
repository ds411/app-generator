# App definition reference

An app definition is one YAML file that describes an application: its
data model, its operations, its pages, and its UI. appgen validates the
file and generates the code of an app from it, for one binding (a target
stack). This page is the reference for each section of the file, with
examples. [ADR 0002](adr/0002-app-definition-dsl-v0.md) and
[ADR 0003](adr/0003-ui-dsl.md) give the reasons for the design.
`examples/project-tracker/app.yaml` is a complete example.

Most examples on this page are parts of a definition, and come from
`examples/project-tracker/app.yaml`. A comment on the first lines of an
example tells where it goes: `# in: entities.Task` is the place of the
example in a definition (the default is the top level), and
`# example: room-booking` names the example that it comes from
(`examples/room-booking/app.yaml`). `tests/test_docs.py` puts each
example into its example definition, and checks that the result is
valid.

## Contents

- [The file](#the-file)
- [Names and IDs](#names-and-ids)
- [app](#app)
- [entities](#entities)
- [seed](#seed)
- [operations](#operations)
- [pages](#pages)
- [workflows](#workflows)
- [apis](#apis)
- [ui](#ui)
  - [theme](#theme)
  - [tokens](#tokens)
  - [badges](#badges)
  - [layouts](#layouts)
  - [navigation](#navigation)
  - [Actions](#actions)
  - [views](#views)
  - [forms](#forms)
  - [dashboards](#dashboards)
  - [Grids](#grids)
  - [UI states and defaults](#ui-states-and-defaults)
- [auth](#auth)
- [access](#access)
- [translations](#translations)
- [Extension keys](#extension-keys)
- [Reserved sections](#reserved-sections)
- [Validation](#validation)

## The file

The file is YAML 1.1. The top level has these keys:

| Key          | Required | Content                                                       |
| ------------ | -------- | ------------------------------------------------------------- |
| `version`    | Yes      | The DSL version. The only version is `0`.                     |
| `app`        | Yes      | The name, the title, and the description of the app.          |
| `entities`   | Yes      | The data model: a mapping from entity name to entity.         |
| `operations` | No       | A mapping from operation name to operation.                   |
| `pages`      | No       | A mapping from page name to page (the routes of a front end). |
| `ui`         | No       | The design tokens, layouts, menus, views, forms, and dashboards. |
| `apis`       | No       | The third-party APIs that the app calls (OpenAPI documents).  |
| `seed`       | No       | The records that the apps start with, for each entity.        |

A minimal definition:

```yaml
version: 0

app:
  name: notes
  title: Notes

entities:
  Note:
    display_field: title
    fields:
      title: { type: string, required: true, max_length: 200 }
      body: { type: text }

operations:
  create_note: { kind: create, entity: Note }
  list_notes: { kind: list, entity: Note }
```

To get completion and checks in an editor with a YAML language server,
put this line at the top of the file:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ds411/app-generator/main/schema/app.schema.json
```

YAML 1.1 reads `yes`, `no`, `on`, and `off` as booleans. Put quotes
around such a value when it is a name, for example an enum value
`"on"`. If a boolean is where a string must be, `appgen validate` says
that YAML read the value as a boolean, and gives its file, line, and
column.

## Names and IDs

Each collection of named elements is a mapping from the name to the
element, never a list. The name rules:

| Element                                  | Rule                  | Example           |
| ---------------------------------------- | --------------------- | ----------------- |
| App name                                 | `^[a-z][a-z0-9-]*$`   | `project-tracker` |
| Entity                                   | `^[A-Z][A-Za-z0-9]*$` | `Task`            |
| Field, relation, param, operation, page, enum value, API, UI element | `^[a-z][a-z0-9_]*$` | `due_date` |
| Operation of an API (its operation ID)   | `^[A-Za-z_][A-Za-z0-9_]*$` | `getPublicHolidays` |
| Seed record key                          | `^[A-Za-z0-9_]+$`     | `a101`, `hq`      |
| Token and token group                    | `^[a-z0-9][a-z0-9_]*$` | `600`, `primary` |
| Icon (a [Lucide](https://lucide.dev) name) | `^[a-z][a-z0-9-]*$` | `folder-kanban`   |

`id` is reserved: each entity has an implicit primary key `id` of type
`uuid`.

Each element has an **ID**: the mapping keys from the root to the
element, with dots. Traces in the generated code refer to elements by
ID ([traces.md](traces.md)).

| Element      | ID                                         |
| ------------ | ------------------------------------------ |
| App          | `app`                                      |
| Entity       | `entities.Task`                            |
| Field        | `entities.Task.fields.title`               |
| Relation     | `entities.Task.relations.project`          |
| Entity rule  | `entities.Booking.rules.ends_after_start`  |
| Operation    | `operations.complete_task`                 |
| Param        | `operations.assign_task.params.note`       |
| Page         | `pages.task_board`                         |
| Page action  | `pages.task_detail.actions.delete`         |
| API          | `apis.holidays`                            |
| API operation | `apis.holidays.operations.getPublicHolidays` |
| Seed of an entity | `seed.Room`                            |
| Seed record  | `seed.Room.records.a101`                   |
| Token        | `ui.tokens.color.primary`                  |
| View column  | `ui.views.task_table.columns.title`        |
| Form field   | `ui.forms.new_task.fields.title`           |

A new element, or a new order of the elements, does not change the ID
of other elements. A rename changes the ID of the element and of all
elements under it.

## app

| Key           | Required | Content                                           |
| ------------- | -------- | ------------------------------------------------- |
| `name`        | Yes      | The technical name, for example the package name. |
| `title`       | Yes      | The display name.                                 |
| `description` | No       | Text.                                             |

## entities

An entity is a type of record, for example `Task`. Each entity is a
database table in the Next.js and FastAPI apps, and a mock data set in
the React app.

| Key             | Required | Content                                                    |
| --------------- | -------- | ---------------------------------------------------------- |
| `fields`        | Yes      | A mapping from field name to field, with one or more fields. |
| `relations`     | No       | A mapping from relation name to relation.                  |
| `description`   | No       | Text.                                                      |
| `label`, `plural_label` | No | Display names. The default comes from the entity name.  |
| `display_field` | No       | The field that names a record in lists and references.    |
| `crud`          | No       | The CRUD shorthand: operations, views, and forms (see below). |
| `rules`         | No       | Rules over more than one field or record (see [Entity rules](#entity-rules)). |

### The CRUD shorthand

`crud` asks for the CRUD operations of an entity, and optionally for a
default table view, detail view, and forms. The loader expands it
before validation ([ADR 0008](adr/0008-crud-shorthand.md)). The names
are the same as the names of the explicit form, so the element IDs and
the traces stay the same.

| Form                       | Gives                                                             |
| -------------------------- | ----------------------------------------------------------------- |
| `crud: true`               | `create_<entity>`, `read_<entity>`, `update_<entity>`, `delete_<entity>`, and `list_<plural>`. |
| `crud: [create, list]`     | Only these operations.                                            |
| `crud: { operations, views, forms }` | `operations` (default: all five), `views` (`table`: `<entity>_table`, `detail`: `<entity>_detail`), and `forms` (`create`: `new_<entity>`, `update`: `edit_<entity>`). |

`<entity>` is the entity name in snake case, for example `stock_item`.
`<plural>` comes from `plural_label` (`People` gives `list_people`), or
else from the entity name (`Category` gives `list_categories`). An
operation, a view, or a form with the same name in the definition wins
over the expanded one. The default table shows the fields and the
single relations, the detail view shows them in one section, and the
forms have all fields and relations except `one_to_many` relations.

```yaml
entities:
  Comment:
    crud: [create, list, delete]
    fields:
      body: { type: text, required: true }
```

### Fields

| Type       | Meaning                              | Options                               |
| ---------- | ------------------------------------ | ------------------------------------- |
| `string`   | A short line of text.                | `min_length`, `max_length`, `pattern` |
| `text`     | Long text with line breaks.          | `min_length`, `max_length`            |
| `integer`  | A whole number.                      | `min`, `max`                          |
| `decimal`  | An exact decimal number.             | `min`, `max`, `precision`, `scale`    |
| `boolean`  | True or false.                       |                                       |
| `date`     | A calendar date.                     |                                       |
| `datetime` | A date and time with a time zone.    |                                       |
| `uuid`     | A UUID.                              |                                       |
| `email`    | An email address.                    | `max_length`                          |
| `url`      | A URL.                               | `max_length`                          |
| `enum`     | One value from a fixed list.         | `values` (required)                   |
| `json`     | A JSON value.                        |                                       |

All fields also take `description`, `label`, `required` (default
`false`), `unique` (default `false`), `default`, `format`, and
`computed` (see [Computed fields](#computed-fields)).

`format` is the display format of the field in all views: the table
columns, the cards, the detail views, the forms, and the stat widgets of
the dashboards. The formats are the same as the formats of a table
column (see [views](#views)), and each format must suit the field type,
for example `currency` for an `integer` or a `decimal` field. A column
or a stat widget can set another format. In a form, a number field with
the format `number`, `currency`, or `percent` shows its value in the
format next to the input. The front ends use `Intl.NumberFormat`.

`currency` gives the currency of the `currency` format: an ISO 4217
code, for example `EUR`. It is for `integer` and `decimal` fields. The
default is `USD`. The views, the forms, and the stat widgets of the
dashboards use the currency of the field. `appgen validate` rejects a
code that is not an ISO 4217 code.

```yaml
# in: entities.Project
fields:
  key:
    type: string
    description: A short code for the project.
    required: true
    unique: true
    pattern: "^[A-Z]{2,6}$"
  status:
    type: enum
    values: [planned, active, on_hold, done]
    default: planned
  budget: { type: decimal, min: 0, precision: 12, scale: 2, format: currency }
  fee: { type: decimal, min: 0, format: currency, currency: EUR }
```

### Computed fields

A computed field gets its value from other fields. `computed` gives the
expression. The records do not store the value: the apps compute it
when they show or return a record. A computed field is an `integer` or a
`decimal` field, without `required`, `unique`, or `default`. A form
cannot have a computed field, and the default forms of the CRUD
shorthand leave it out.

An expression has:

| Part                 | Example                         | Meaning                                         |
| -------------------- | ------------------------------- | ----------------------------------------------- |
| A number             | `1.2`                           | A literal.                                      |
| A field path         | `quantity`, `room.hourly_rate`  | An `integer` or a `decimal` field, not a computed field. |
| `+`, `-`, `*`, `/`   | `price * quantity`              | The operators, with the usual order.            |
| `( )`                | `(a + b) / 2`                   | A group.                                        |
| `hours(start, end)`  | `hours(starts_at, ends_at)`     | The hours between two `date` or `datetime` fields. |
| `days(start, end)`   | `days(start_date, due_date)`    | The days between two `date` or `datetime` fields.  |

An empty operand, or a division by zero, gives an empty value. The apps
round a `decimal` field to its `scale`, and an `integer` field to a
whole number. The FastAPI app returns the value in the read schema (a
property of the model), and the front ends compute it in the views.

```yaml
# example: room-booking
# in: entities
Booking:
  fields:
    starts_at: { type: datetime, required: true }
    ends_at: { type: datetime, required: true }
    cost:
      type: decimal
      scale: 2
      format: currency
      computed: hours(starts_at, ends_at) * room.hourly_rate
```

### Entity rules

`rules` is a mapping from rule name to rule. A rule checks more than
one field of a record, or more than one record. The back ends (FastAPI
and Next.js) check the rules when they create or change a record. The
React app has mock data and no back end, so it does not check them.

| `kind`       | Keys                                   | Check                                         | Error |
| ------------ | -------------------------------------- | --------------------------------------------- | ----- |
| `compare`    | `field`, `op`, `other`, `message`      | `field op other`. `op` is `eq`, `ne`, `lt`, `lte`, `gt`, or `gte`. | 422 |
| `unique`     | `fields` (two or more), `message`      | No two records have the same values. The table has a unique constraint. | 409 |
| `no_overlap` | `start`, `end`, `scope`, `message`     | The ranges `[start, end)` of two records with the same `scope` values do not overlap. | 409 |

The fields of a rule are stored fields of the entity. `unique` and
`scope` also take `many_to_one` and `one_to_one` relations (their
foreign keys). A compare rule compares two numbers, two dates, two
date-times, or two texts. The start and the end of a `no_overlap` rule
are two `date` or two `datetime` fields. An empty value passes a
compare rule and a `no_overlap` rule: `required` checks it. The mock
data keeps the compare and the unique rules.

```yaml
# example: room-booking
# in: entities
Booking:
  rules:
    ends_after_start:
      kind: compare
      field: ends_at
      op: gt
      other: starts_at
      message: The end must be after the start.
    no_double_booking:
      kind: no_overlap
      start: starts_at
      end: ends_at
      scope: [room]
      message: The room has another booking at this time.
```

### Relations

| Kind           | Meaning                                            | Foreign key          |
| -------------- | -------------------------------------------------- | -------------------- |
| `many_to_one`  | Many records of this entity refer to one target.   | On this entity.      |
| `one_to_many`  | One record of this entity has many target records. | On the target.       |
| `one_to_one`   | One record of this entity refers to one target.    | On this entity.      |
| `many_to_many` | Many records on each side.                         | In a join table.     |

| Key           | Content                                                                 |
| ------------- | ----------------------------------------------------------------------- |
| `kind`        | Required. One of the kinds above.                                       |
| `target`      | Required. The target entity.                                            |
| `inverse`     | The relation on the target that is the other side. Required for `one_to_many`, where it is a `many_to_one` relation back to this entity. |
| `required`    | `many_to_one` and `one_to_one` only.                                    |
| `on_delete`   | `restrict`, `cascade`, or `set_null`. `many_to_one` and `one_to_one` only. |
| `description`, `label` | Text.                                                          |

```yaml
# in: entities
Task:
  relations:
    project:
      kind: many_to_one
      target: Project
      required: true
      on_delete: cascade
      inverse: tasks
Project:
  relations:
    tasks: { kind: one_to_many, target: Task, inverse: project }
    members: { kind: many_to_many, target: Person }
```

## seed

The optional `seed` section gives the records that the apps start with,
for example the rooms of an office or the categories of a shop. It maps
an entity name to the seed of the entity
([ADR 0021](adr/0021-seed-data.md)):

```yaml
# not valid alone: the entities Office, Room, and Feature are not in an example.
seed:
  Office:
    records:
      hq: { name: Head office, opened_on: 2020-03-01 }
      lisbon: { name: Lisbon office }
  Room:
    mock: 5
    records:
      a101: { code: A101, capacity: 8, office: hq, features: [screen, board] }
      b201: { code: B201, office: lisbon }
  Feature:
    records:
      screen: { label: Screen }
      board: { label: Whiteboard }
```

| Key       | Content                                                                    |
| --------- | -------------------------------------------------------------------------- |
| `records` | A mapping from a record key to the values of the record.                   |
| `file`    | A local data file with more records, from the folder of the definition: `.yaml`, `.yml`, `.json`, or `.csv` (see [Data files](#data-files)). |
| `mock`    | The number of generated records in addition to the seed records: an integer, 0 or more. The default is 0. |

- Each record is an element, for example `seed.Room.records.a101`. A
  record key has only letters, digits, and `_`.
- The key gives the ID of the record: a UUID (version 5) from the app
  name, the entity name, and the key. A change of another record, or a
  new order of the records, does not change the ID. A rename of the key,
  the entity, or the app changes it.
- A record gives its values by field name and by relation name. A
  `many_to_one` or `one_to_one` relation takes the key of a seed record
  of the target entity, and a `many_to_many` relation takes a list of
  keys. A `one_to_many` relation takes no value: give the key in the
  `many_to_one` relation of the records on the other side.
- A `one_to_one` relation and its inverse are one link. Give the key on
  one side, or on both sides with the same partner.
- A field that the record does not give gets its default, or no value.
  A required field without a default, and a required relation, need a
  value. A computed field takes no value.
- Without a seed, an entity has generated mock records: 12, or the
  number of the extension key `x-mock-count`. With a seed, the entity has
  its seed records and `mock` generated records. A generated record can
  refer to a seed record.
- The React app has the seed records first in its mock data. The
  Next.js seed (`pnpm db:seed`) adds each seed record that the database
  does not have, by ID, and adds generated records only if all tables
  are empty. The FastAPI binding excludes the elements of `seed` for now,
  so `appgen generate` makes no gap for them.

The values:

| Field type                                 | Value                                              |
| ------------------------------------------ | -------------------------------------------------- |
| `string`, `text`, `email`, `url`, `enum`, `uuid` | A text. An `email` has the form `name@domain`, a `url` starts with `http://` or `https://`. |
| `integer`                                  | An integer.                                        |
| `decimal`                                  | A number.                                          |
| `boolean`                                  | `true` or `false`.                                 |
| `date`                                     | An ISO 8601 date, for example `2026-01-05`.        |
| `datetime`                                 | An ISO 8601 date-time, for example `2026-01-05T09:30:00Z`. A date-time without an offset is in UTC. |
| `json`                                     | Any value.                                         |

### Data files

Many records, for example an export of another system, fit better into
a data file next to the definition. `file` names the file, from the
folder of the definition. An entity can have `records` and `file`, but a
key cannot be in both.

```yaml
# not valid alone: the data files are not next to an example.
seed:
  Room:
    file: data/rooms.csv
  Feature:
    file: data/features.yaml
```

A YAML or a JSON file is a mapping from a record key to a record, as
`records`:

```yaml
# not valid alone: the text of a data file, not of a definition.
screen: { label: Screen }
board:
  label: Whiteboard
```

```json
{
  "screen": { "label": "Screen" },
  "board": { "label": "Whiteboard" }
}
```

A CSV file has a header with the column `key`, and one column for each
field and relation that it gives. Each row is a record:

```text
key,code,capacity,bookable,opened_on,office,features
a101,A101,8,true,2020-03-01,hq,screen;board
b201,B201,,false,,lisbon,
```

- An empty cell is no value.
- The loader converts each cell to the type of its field: an `integer`,
  a `decimal` (a number with a `.`), a `boolean` (`true` or `false`), a
  `date` or a `datetime` (ISO 8601), and a `json` value (JSON text). A
  cell that does not convert is an error.
- A `many_to_one` or `one_to_one` cell has a record key. A
  `many_to_many` cell has record keys with `;` between them.
- A column that is not a field or a relation of the entity is an error
  (`unknown-key`).

The records of a file are elements with the same IDs as the records of
`records`, for example `seed.Room.records.a101`. Each diagnostic of a
record gives the path of the file and the line of the record (for a CSV
file, the line of the row). The file must be a local file: appgen reads
no URL. The output manifest records the hash of each data file, so the
same files give the same app.

`appgen validate` checks each value against the type and the options of
its field (`values`, `min`, `max`, `min_length`, `max_length`,
`pattern`, and `precision`). It also checks that each key of a relation
exists, that the records of an entity have different values in each
`unique` field, and that they keep the `compare`, `unique`, and
`no_overlap` rules of the entity. An error in a value gives the line of
the value. Put quotes around a text that YAML reads as a number or a
boolean, for example `code: "101"`.

## operations

An operation is an action of the app on an entity. The bindings
generate the code of the CRUD and list operations: a REST endpoint in
the FastAPI app, a server action in the Next.js app, and a data access
function in the React app.

| Key           | Content                                                                  |
| ------------- | ------------------------------------------------------------------------ |
| `kind`        | Required. `create`, `read`, `update`, `delete`, `list`, or `custom`.     |
| `entity`      | Required. The entity of the operation.                                   |
| `description` | Text. A custom operation shows it in its extension file.                 |
| `params`      | `custom` only. A mapping from parameter name to a field (the field keys). |
| `returns`     | `custom` only. An entity name, or `none` (the default).                  |
| `apis`        | `custom` only. The names of the [apis](#apis) that the logic calls.       |

The logic of a `custom` operation is a **generation gap**: the binding
generates the signature and the endpoint, and an extension file holds
the body, which the app developer writes
([traces.md](traces.md#generation-gaps)).

```yaml
operations:
  list_tasks: { kind: list, entity: Task }
  assign_task:
    kind: custom
    entity: Task
    description: Assign a task to a person, and tell the person.
    params:
      assignee_id: { type: uuid, required: true }
      note: { type: text, max_length: 500 }
    returns: Task
```

## pages

A page is a route of a front-end app. The back-end binding (FastAPI)
ignores the pages.

| Key           | Content                                                                 |
| ------------- | ----------------------------------------------------------------------- |
| `path`        | Required. The URL path, with `{param}` segments, for example `/projects/{id}`. |
| `title`       | Required.                                                               |
| `entity`      | The main entity. A path parameter of a page with an entity is a field of the entity, usually `id`. |
| `description` | Text under the title.                                                   |
| `layout`      | A layout of `ui.layouts`. Default: `ui.defaults.layout`.                |
| `content`     | One of `view: <view>`, `form: <form>`, `dashboard: <dashboard>`, or `custom: true` (a generation gap). |
| `actions`     | Actions in the page header (see [Actions](#actions)).                   |
| `breadcrumb`  | The label in the breadcrumbs. Default: the label of the menu item of the page, else the title, or the display field of the record for a page with an entity and a path parameter. |
| `arrangement` | Layout hints: the order and the place of the title, the actions, and the content (see below). |

The parent of a page in the breadcrumbs is the page whose path is the
longest prefix of the page path. Two pages cannot have the same path.

Without `arrangement`, a page shows a header with the title and the
description on the left and the actions on the right, and the content
under the header. `arrangement` changes this layout. It has `regions`,
a list of `title` (the title and the description), `actions`, and
`content`, and `columns` (1 to 4, default 2). The regions fill a grid
of `columns` columns in their order, row by row. Each region takes one
cell, and `content` takes a full row. In a row with more than one
region, the last region moves to the end of its cell. Screens narrower
than the `md` breakpoint of Tailwind CSS have one column. A region that
the list does not have does not show, but `content` must be in the
list.

```yaml
pages:
  project_detail:
    path: "/projects/{id}"
    title: Project
    entity: Project
    content: { view: project_detail }
    # The actions above the title, and the content under them.
    arrangement: { regions: [actions, title, content], columns: 1 }
```

```yaml
pages:
  task_detail:
    path: "/tasks/{id}"
    title: Task
    entity: Task
    content: { view: task_detail }
    actions:
      delete:
        kind: operation
        operation: delete_task
        label: Delete
        icon: trash-2
        variant: destructive
        confirm: { title: "Delete the task?", confirm_label: Delete }
        on_success: { toast: The task is deleted., navigate: task_board }
```

## workflows

A workflow is a state machine on an enum field of an entity. The values
of the field are the states. The apps reject a change of the field that
no transition allows:

```yaml
# example: room-booking
workflows:
  booking_status:
    entity: Booking
    field: status
    initial: requested
    message: This change of the booking status is not allowed.
    transitions:
      confirm: { from: [requested], to: confirmed, label: Confirm }
      cancel: { from: [requested, confirmed], to: cancelled, label: Cancel }
```

- `field` is a stored enum field of `entity`. A field has one workflow.
- `initial` (optional) is the state of a new record. Without it, a new
  record can have any state.
- Each transition allows a change from each value in `from` to `to`.
  `to` is not in `from`.
- `message` (optional) is the error message of a change that no
  transition allows.
- A change to the same state, and a change from or to no value, pass.

The FastAPI app gives a 422 error, the Next.js app a `ValidationError`,
and the React app (mock data) a `TransitionError`. The FastAPI app has a
test of each workflow.

## apis

The optional `apis` section names the third-party APIs that the app
calls, for example a payment service or the public holidays. An OpenAPI
document (3.0 or 3.1, YAML or JSON) describes each API. The bindings
generate a typed client for the operations in the list, and the
hand-written code of the app calls the client
([ADR 0019](adr/0019-third-party-apis.md)).

```yaml
apis:
  holidays:
    description: The public holidays of the countries.
    document: apis/public-holidays.openapi.yaml
    base_url_env: HOLIDAYS_API_URL
    operations: [getPublicHolidays, getNextPublicHolidays]
  exchange_rates:
    document: apis/exchange-rates.openapi.json
    base_url_env: EXCHANGE_RATES_API_URL
    security: { scheme: ApiKeyAuth, env: EXCHANGE_RATES_API_KEY }
    expose: true
    operations:
      getLatestRates: {}
      convertAmount: { description: Convert a budget to another currency. }
```

| Key            | Content                                                                   |
| -------------- | ------------------------------------------------------------------------- |
| `document`     | Required. The path of the OpenAPI document, from the folder of the definition. |
| `base_url_env` | Required. The environment variable of the base URL. Its default value is the first server of the document. |
| `operations`   | Required. A list of operation IDs, or a mapping from operation ID to an operation with an optional `description`. |
| `security`     | The credential of each request: `scheme`, a security scheme of the document, and `env`, the environment variable of the secret. The front-end builds make a variable with the prefix `NEXT_PUBLIC_` or `VITE_` public, so `env` cannot have it. Without `security`, the requests have no credential. |
| `expose`       | `true`: the FastAPI app has an endpoint for each operation, which calls the API with its secret, so that a front end can use the API. The default is `false`. |
| `title`        | The name of the API. The default is the title of the document.            |
| `description`  | Text.                                                                     |

- The document must be a local file. appgen reads no URL, and rejects a
  `$ref` to another file. The output manifest records the hash of each
  document, so the same files give the same app.
- Each operation ID must exist in the document, and must be a valid ID
  segment (letters, digits, and `_`).
- The clients support an API key in a header or a query parameter, and
  a bearer token. They send path, query, and header parameters, and
  JSON bodies, and they read JSON answers.
- The client has only the selected operations and the schemas that they
  use. Each answer has an example: the example of the document, or a
  sample from the schema.
- A custom operation names the APIs of its logic in `apis`. In the
  FastAPI app, its extension function then gets the clients of these
  APIs as arguments. The Next.js app has a server-only client for each
  API in `src/shared/api/<api>/`, which the extension file imports.
- The React app calls the APIs in the browser, and a browser app cannot
  keep a secret. Thus only an API without `security` or with `expose`
  gets a client in `src/shared/api/<api>/`. With mock data, the client
  gives the example answers. For an API with `security` and without
  `expose`, `appgen generate` gives a warning: set `expose: true`, or
  call the API in a custom operation of the FastAPI app, and set
  `x-react-data: api`.
- With `expose: true`, the FastAPI app has the endpoint
  `/apis/<api>/<operation>` (in kebab case, for example
  `/apis/exchange-rates/get-latest-rates`) for each operation, with the
  method of the operation. The endpoint takes all parameters of the
  operation as query parameters, with their names in the document, and
  the body of the operation as its body. It gives the answer of the API.
  An error of the API, an answer that does not agree with the document,
  or no answer gives 502. With `auth`, the endpoints need a signed-in
  user, but the roles do not apply to them. With `x-react-data: api`,
  the client of the React app calls these endpoints, and sends the token
  of the signed-in user.
- An exposed API cannot have an operation with a parameter that a query
  parameter cannot hold (an object, or a list of lists), or two
  parameters with the same name (`unsuitable-operation`). Call such an
  operation in a custom operation.
- The environment variables of the apps (for example `DATABASE_URL`)
  are reserved. Two keys cannot use the same variable.
- A view can show the answer of an operation without hand-written code:
  see [Views of API data](#views-of-api-data).

## ui

The `ui` section describes the front ends. All its keys are optional.
The back-end binding ignores it.

### References

UI elements refer to other elements:

| Target                    | Syntax                     | Example                 |
| ------------------------- | -------------------------- | ----------------------- |
| Token                     | The token path in braces   | `"{color.primary}"`     |
| Entity                    | The entity name            | `entity: Task`          |
| Field or relation         | A field path               | `title`, `project.name` |
| Operation, page, view, form, dashboard, badge set, layout, menu | The name | `form: edit_task` |
| Breakpoint                | The breakpoint token name  | `md`                    |

A **field path** starts at the entity of the element. Each segment
before the last is a `many_to_one` or `one_to_one` relation. A path
that ends at a relation shows the display field of the target.

Style values (colors, gaps, widths) take token references only, so all
style values come from the tokens.

### theme

```yaml
ui:
  theme:
    default_mode: system   # light, dark, or system
    mode_toggle: true      # a light and dark switch in the top bar
```

### tokens

The design tokens follow the W3C Design Tokens (DTCG) format, with
fixed top-level groups. A **token** is a mapping with `$value`. A
**group** is a mapping without `$value`, and groups can nest. Tokens
and groups can have `$description`.

| Group            | Value                                                          |
| ---------------- | -------------------------------------------------------------- |
| `color`          | `#rgb`, `#rrggbb`, `#rrggbbaa`, `oklch()`, `rgb()`, or `hsl()` |
| `font_family`    | A family name, or a list of names.                             |
| `font_size`      | A number with `px` or `rem`.                                   |
| `font_weight`    | An integer from 1 to 1000.                                     |
| `line_height`    | A number.                                                      |
| `letter_spacing` | A number with `px`, `rem`, or `em`.                            |
| `typography`     | `font_family`, `font_size`, `font_weight`, `line_height`, and `letter_spacing`. |
| `spacing`, `size`, `radius` | A number with `px` or `rem`, or `0`.                |
| `shadow`         | `color`, `offset_x`, `offset_y`, `blur`, `spread`, and `inset`, or a list of these. |
| `breakpoint`     | A minimum screen width with `px`.                              |
| `duration`       | A number with `ms`.                                            |

A value is a literal or a reference to a token of the same type.
`$modes` gives a token another value in the `light` or the `dark` mode.

`motion` is not a group. It is one setting, `{ $value: <motion> }`,
for the animations of the charts, the dialogs, the menus, and the
transitions: `full` (the default), `reduced` (no animations for users
who ask their system for reduced motion), or `none` (no animations).

```yaml
ui:
  tokens:
    color:
      blue:
        600: { $value: "#2563eb" }
        400: { $value: "#60a5fa" }
      primary:
        $value: "{color.blue.600}"
        $modes: { dark: "{color.blue.400}" }
    spacing:
      4: { $value: 1rem }
    radius:
      lg: { $value: 0.625rem }
    breakpoint:
      md: { $value: 768px }
```

The front-end bindings write each color token, and each token with a
dark value, as a CSS variable in `:root` and `.dark`. A color token
with the name of a shadcn/ui variable themes the components:
`color.primary_foreground` gives `--primary-foreground`. `radius.lg`
gives `--radius`. The other tokens are Tailwind CSS theme variables,
for example `spacing.4` gives `--spacing-4`.

### badges

A badge set gives each value of an `enum` field a label, a color, and
an icon.

```yaml
ui:
  badges:
    task_status:
      field: Task.status
      values:
        todo: { label: To do, color: "{color.status.neutral}", icon: circle }
        done: { label: Done, color: "{color.status.success}", icon: circle-check }
```

### layouts

A layout is an app shell with regions:

| Region    | Keys                                                                        |
| --------- | --------------------------------------------------------------------------- |
| `sidebar` | `navigation` (a menu), `title`, `icon`, `width` (a token), `mode` (`expanded`, `icons`, `drawer`, or `hidden`), `side` (`left` or `right`). |
| `topbar`  | `breadcrumbs`, `mode_toggle`, `search` (booleans), and `actions`.           |
| `content` | `max_width` and `padding` (tokens).                                         |
| `footer`  | `text`.                                                                     |

`responsive` maps a breakpoint to overrides of the region keys. An
override applies on screens narrower than the breakpoint, and the
smallest breakpoint wins.

```yaml
ui:
  layouts:
    app_shell:
      sidebar: { navigation: main, title: Project Tracker, icon: folder-kanban, width: "{size.sidebar}" }
      topbar:
        search: true
        actions:
          new_task: { kind: form, form: new_task, label: New task, icon: plus }
      content: { max_width: "{size.content}", padding: "{spacing.8}" }
      responsive:
        lg: { sidebar: { mode: icons } }
        md: { sidebar: { mode: drawer }, topbar: { search: false } }
```

### navigation

A menu has `items`, `groups` with `items`, or both. An item has `page`
(required), `label` (default: the page title), `icon`, and `items` (one
level of sub-items). A group has `label`, `icon`, `collapsible`, and
`items`.

```yaml
ui:
  navigation:
    main:
      items:
        dashboard: { page: dashboard, icon: layout-dashboard }
      groups:
        work:
          label: Work
          items:
            projects: { page: projects, icon: folder-kanban }
```

### Actions

Views, pages, and top bars have actions: a mapping from a name to an
action. Each action has `kind`, and `label`, `icon`, `variant`
(`default`, `secondary`, `outline`, `ghost`, or `destructive`), and
`confirm` (`title`, `message`, `confirm_label`).

| Kind        | Keys                                                                    |
| ----------- | ----------------------------------------------------------------------- |
| `navigate`  | `page`, and `params`: a mapping from a path parameter to a field path.  |
| `form`      | `form`. In a row or on a record page, an edit form gets the record.     |
| `operation` | `operation`: runs the operation on the record, for example a delete. A custom operation with `params` needs a form action. |
| `custom`    | A generation gap.                                                       |

`form` and `operation` actions take `on_success`: `toast` and
`navigate` (a page).

The front ends show each action one time on a page. If the top bar of
the page has the same action (the same kind, and the same form,
operation, or page), the page header and the view of the page do not
show it. A trace in the code of the page or the view still refers to
the hidden action.

A page action takes `placement` to choose where it shows:

| Placement | The action shows                                                    |
| --------- | ------------------------------------------------------------------- |
| `page`    | In the page header. The top bar does not show the same action on the page. |
| `topbar`  | In the top bar of the layout of the page, on the page only. The page header does not show it. |
| `both`    | In the page header and in the top bar, on the page only.           |

Without `placement`, the rule above applies. `topbar` and `both` need a
layout with a top bar, and an action that does not need the record of
the page (the top bar has no record). Only page actions take
`placement`.

```yaml
pages:
  project_detail:
    actions:
      new_task: { kind: form, form: new_task, label: New task, placement: page }
```

### views

A view shows the records of one entity. Each view has `kind`, `entity`,
and optional `title`, `description`, `actions`, and `states`. A view
can also show the answer of an API operation in place of the records:
see [Views of API data](#views-of-api-data).

**Table** (`kind: table`):

| Key            | Content                                                         |
| -------------- | --------------------------------------------------------------- |
| `columns`      | Required. A mapping from column name to column.                 |
| `sort`         | `field` and `direction` (`asc` or `desc`).                      |
| `filters`      | A mapping from filter name to filter.                           |
| `pagination`   | `page_size` and `page_sizes`.                                   |
| `row_actions`  | Actions of each row.                                            |
| `row_click`    | The row action that a click on a row runs.                      |
| `selection`    | Boolean: check boxes on the rows.                               |
| `bulk_actions` | Actions of the selected rows.                                   |

A column has `field` (default: the column name), `label`, `format`,
`badge`, `width` (a `size` token), `align` (`start`, `center`, `end`),
`sortable`, `link` (a page), and `hide_below` (a breakpoint). The
formats are `text`, `number`, `currency`, `percent`, `date`,
`datetime`, `relative_time`, `boolean`, `badge`, `email`, `url`, and
`avatar`. The default format is the `format` of the field, else a
format for the field type.

A filter has `kind`: `search` (`fields`), `select` (`field`,
`multiple`), `boolean` (`field`), or `date_range` (`field`). All
filters take `label` and `default`.

```yaml
ui:
  views:
    task_table:
      kind: table
      entity: Task
      columns:
        title: { label: Task, link: task_detail, width: "{size.column_lg}" }
        status: { badge: task_status }
        assignee: { format: avatar }
        due_date: { format: date, align: end }
      sort: { field: due_date }
      filters:
        search: { kind: search, fields: [title] }
        status: { kind: select, field: status, multiple: true }
```

**Card list** (`kind: cards`): `card` (`title`, `subtitle`, `badge`,
`fields`, `footer`), `grid`, and the `sort`, `filters`, `pagination`,
and `row_actions` of a table.

**Board** (`kind: board`): `group_by` (an `enum` field), `columns` (a
mapping from enum value to `label`, `color`, and `limit`), `card`, and
`move` (an update or custom operation that runs when a card moves to
another column), and `responsive`. `responsive` has `below` (a
breakpoint token) and `layout`: on screens narrower than the
breakpoint, `stack` shows the columns one under the other, and `scroll`
shows each column almost as wide as the screen, with snap scroll.
Without `responsive`, the columns scroll sideways.

**Calendar** (`kind: calendar`): the records on a calendar, in a week
or a month. `start` (a `date` or a `datetime` field) gives the day and
the time of a record, and the optional `end` (a field of the same type)
gives its end: a record shows on each day from its start to its end.
`label` is the text of a record (default: the display field), `mode` is
the first mode (`week` or `month`, default `month`), and `link` is a
page that a record opens. The user can switch the mode, and go to the
previous, the next, or the current week or month. The weeks start on
Monday.

```yaml
# example: room-booking
ui:
  views:
    booking_calendar:
      kind: calendar
      entity: Booking
      start: starts_at
      end: ends_at
      mode: week
      link: booking_detail
```

**Detail** (`kind: detail`): one record, from the path parameter of the
page. `header` (`title`, `subtitle`, `badges`), `sections` (`title`,
`description`, `fields`, `columns`, or `custom: true`), `tabs`
(`label`, `icon`, and `sections`, or `relation` and `view`, or
`custom: true`), and `actions`.

```yaml
ui:
  views:
    task_detail:
      kind: detail
      entity: Task
      header: { title: title, subtitle: project, badges: [status, priority] }
      sections:
        summary: { title: Summary, fields: [assignee, due_date, estimate_hours], columns: 3 }
      tabs:
        comments: { label: Comments, icon: message-square, relation: comments, view: comment_table }
        activity: { label: Activity, custom: true }
```

#### Views of API data

A table, a card list, or a detail view can show the answer of an
operation of an API (see [apis](#apis) and
[ADR 0022](adr/0022-api-views.md)). The view has `source:
apis.<api>.operations.<id>` in place of `entity`, and `params`: the
value of each parameter of the operation, by its name in the document.
A value is a literal, or `$route.<name>` for a path parameter of the
page. Each required parameter needs a value, and the operation must
have no body.

- A table or a card list needs an answer that is a list of objects. If
  the list is in a property of the answer, `items` names the property,
  for example `data.items`.
- A detail view needs an answer that is an object. It has `header`
  (`title`, `subtitle`) and `sections` (`title`, `description`,
  `fields`, `columns`). An answer that is null shows the empty state.
- The columns, the card (`title`, `subtitle`, `fields`, `footer`), the
  `sort`, and the search filters (`kind: search`, `fields`) name the
  properties of an item, also nested properties with dots, for example
  `author.name`. A column has `field` if its name is not the property. A
  shown property holds a text, a number, a boolean, or a list of these.
- The default format of a property comes from its schema: `date`,
  `datetime`, `email`, `url`, `number`, `boolean`, `badge` for an enum,
  else `text`.
- The view sorts, searches, and pages (`pagination`) the loaded items.
  Its items are not records, so it has no actions, no row actions, no
  bulk actions, no selection, no tabs, and only search filters.
- The page of the view has no `entity`, and its path has each `$route`
  parameter of the view.

The Next.js app calls the operation in the server component of the
page, at each request, with the server client of the API. An error of
the API shows the error state of the view. The React app calls the
operation in the browser: with mock data, the view shows the example
answer of the document. In the React app, the view of an API with a
secret is a gap, unless the API has `expose: true`. With
`x-react-data: api`, the view of an exposed API calls the FastAPI app.

```yaml
pages:
  holidays: { path: /holidays, title: Public holidays, content: { view: public_holidays } }
ui:
  views:
    public_holidays:
      kind: table
      source: apis.holidays.operations.getPublicHolidays
      params: { year: 2026, countryCode: DE }
      columns:
        date: {}
        name: { label: Holiday }
        local_name: { field: localName }
      sort: { field: date }
      filters:
        search: { kind: search, fields: [name, localName] }
```

```yaml
pages:
  country_holidays:
    path: "/holidays/{country}"
    title: Holidays of a country
    content: { view: country_holidays }
ui:
  views:
    country_holidays:
      kind: cards
      source: apis.holidays.operations.getNextPublicHolidays
      params: { countryCode: $route.country }
      card: { title: name, subtitle: date, fields: [localName] }
```

### forms

| Key             | Content                                                            |
| --------------- | ------------------------------------------------------------------ |
| `entity`        | Required.                                                          |
| `operation`     | Required. A `create`, `update`, or `custom` operation of the entity. |
| `mode`          | `dialog` (default), `sheet`, or `page`.                            |
| `title`, `description`, `submit_label`, `cancel_label` | Texts.                      |
| `fields`        | Required. A mapping from a field, relation, or param name to a form field. |
| `sections`      | `title`, `description`, and `fields` (a list of form field names). |
| `grid`          | The column grid.                                                   |
| `rules`         | Rules across fields: `kind: compare` (`field`, `op`, `other`, `message`) or `kind: custom` (a generation gap). |
| `defaults`      | A literal, or `$route.<param>` for a path parameter of the page.  |
| `on_success`    | `toast`, `close`, and `navigate`.                                  |

A form field has `widget`, `label`, `placeholder`, `help`, `span`,
`rows`, `step`, `options`, and `rules` (`required`, `min_length`,
`max_length`, `pattern`, `min`, `max`, each with `value` and
`message`). The widgets are `text`, `textarea`, `number`, `select`,
`radio`, `checkbox`, `switch`, `date`, `datetime`, `relation`, and
`custom` (a generation gap). The default widget comes from the field
type.

```yaml
ui:
  forms:
    new_task:
      entity: Task
      operation: create_task
      mode: dialog
      title: New task
      fields:
        title: { placeholder: "What needs to be done?" }
        project: {}
        priority: { widget: radio }
        due_date: {}
      defaults: { project: $route.id, priority: medium }
      on_success: { toast: The task is created. }
```

### dashboards

A dashboard has `title`, `description`, `grid`, and `widgets`. Each
widget has `kind`, `label`, and `span`:

| Kind     | Keys                                                                      |
| -------- | ------------------------------------------------------------------------- |
| `stat`   | `entity`, `aggregate` (`count`, `sum`, `avg`, `min`, `max`), `field`, `filter`, `format`, `icon`, `color`, `link`. |
| `chart`  | `chart` (`bar`, `line`, `donut`), `entity`, `group_by`, `aggregate`, `field`, `filter`, `badge`. |
| `list`   | `view`, `filter`, `sort`, `limit`, `link`.                                |
| `custom` | A generation gap.                                                         |

The default `format` of a stat widget is the `format` of its field (for
`sum`, `avg`, `min`, and `max`), else `number`.

A filter maps a field path to a value, or to operators (`eq`, `ne`,
`lt`, `lte`, `gt`, `gte`, `in`, `not_in`). `$today` and `$now` are
date values.

```yaml
# in: ui.dashboards.overview
widgets:
  overdue_tasks:
    kind: stat
    label: Overdue tasks
    entity: Task
    aggregate: count
    filter: { due_date: { lt: $today }, status: { ne: done } }
    icon: alarm-clock
    color: "{color.destructive}"
    link: task_board
```

### Grids

A grid has `columns` (1 to 12), `gap` (a `spacing` token), and
`responsive` (a mapping from breakpoint to `columns` and `gap`). Forms,
card lists, and dashboards use grids.

### UI states and defaults

A view can have `states`: `loading` (`indicator`: `skeleton` or
`spinner`, and `text`), `empty`, and `error`, each with `title`, `text`,
`icon`, and `action` (an action of the view, or `retry` for an error).

`ui.defaults` gives the values that elements do not set:

```yaml
ui:
  defaults:
    layout: app_shell
    page_size: 20
    states:
      loading: { indicator: skeleton }
      empty: { title: Nothing here yet, icon: inbox }
      error: { title: Something went wrong, icon: triangle-alert, action: retry }
```

## auth

The optional `auth` section closes the apps: the users sign in with a
user name and a password ([ADR 0011](adr/0011-auth.md)), or with an
OpenID Connect provider ([ADR 0020](adr/0020-providers.md)).

```yaml
# example: room-booking
auth:
  user_entity: Member
  username_field: email
  public_pages: [rooms]
  public_operations: [list_rooms]
  session_hours: 12
  min_password_length: 10
  sign_up:
    fields: [name, email, team]
    default_role: member
    verify_email: true
  password_reset:
    token_minutes: 30
  providers:
    company:
      title: Company account
      issuer: https://login.example.com
      client_id_env: COMPANY_CLIENT_ID
      client_secret_env: COMPANY_CLIENT_SECRET
      create_users: true
      default_role: member
      claims: { name: name }
```

- `user_entity` is the entity of the users. `username_field` is a
  required, unique `string` or `email` field of it.
- `public_pages` and `public_operations` are open without a sign-in.
  All other pages and operations need a signed-in user.
- `session_hours` (1 to 720, default 8) is the time of a session.
- `min_password_length` (8 to 128, default 8) is the lowest number of
  characters of a new password: at a sign-up and at each change.
- `sign_up` lets new users make their own accounts
  ([ADR 0016](adr/0016-sign-up.md)). It is off by default. `fields`
  names the fields of the user entity that the sign-up form asks for.
  It must have each required field without a default, and it cannot
  have the role field or a computed field. With `access`,
  `default_role` is the role of a new user. Without it, a new user gets
  the default of the role field.
- `sign_up.verify_email` makes a new user confirm the email address
  before the first sign-in ([ADR 0023](adr/0023-email-verification.md)).
  It is off by default. The app sends a message with a link to the
  address, and the user can sign in only after the user opens the link.
  `true` gives a link that stays valid for one day. The mapping form
  sets the time: `verify_email: { token_minutes: 60 }` (5 to 10080,
  default 1440). The address is the user name field if its type is
  `email`, else the first required `email` field of the user entity: the
  user entity must have one. The users that an administrator gives a
  password, and the users of a provider, need no verification.
- `password_reset` lets a user who forgot the password set a new one
  with a link in a message ([ADR 0017](adr/0017-password-reset.md)). It
  is off by default. `token_minutes` (5 to 1440, default 60) is the
  time that a link stays valid. A link is valid only one time. The
  delivery of the message (for example an email) is a generation gap.
- `providers` are OpenID Connect providers that the users can sign in
  with, for example the sign-in of the company
  ([ADR 0020](adr/0020-providers.md)). The name of a provider is a
  snake case name. `issuer` is the `https` URL of the provider: the apps
  read its discovery document. `client_id_env` and `client_secret_env`
  name the environment variables of the client of the app at the
  provider. `scopes` (default `[openid, email, profile]`) must include
  `openid`. The claim `username_claim` (default `email`) of the ID
  token gives the user name. With `email`, the provider must not say
  that the email address is not verified. Without `create_users`, the
  user must exist. With `create_users: true`, the first sign-in makes a
  new user: `claims` gives the other fields of the new user from claims
  (field name: claim name), and it must give each required field without
  a default. With `access`, `default_role` is the role of a new user.
  `title` (default: the name) is the text on the sign-in button.
- `password: false` turns off the sign-in with a password: the users
  sign in only with `providers`. It needs a provider, and it cannot
  have `sign_up` or `password_reset`.
- No page can use the path `/sign-in`, `/sign-up` with a sign-up,
  `/verify-email` with `verify_email`, `/forgot-password` and
  `/reset-password` with a password reset, or a path under `/auth/` with
  providers: they are the pages of the front ends.

The FastAPI app has `POST /auth/sign-in` (a bearer token), `GET
/auth/me`, and `PUT /auth/password`, and `python -m app.cli
set-password <user name>`. With `sign_up`, the public endpoint `POST
/auth/sign-up` makes the user and its password in one transaction, and
gives a bearer token. A user name that exists gives 409. With
`verify_email`, the sign-up gives 202 without a token, and sends a link
with a signed token to the address. A sign-in before the user opens the
link gives 403. `POST /auth/verify-email/confirm` confirms the address
with the token, and `POST /auth/verify-email` sends a new link (202 also
for an unknown user name). `EMAIL_VERIFY_URL` is the page of the link. A
password reset link confirms the address too. A provider that says
that the address is verified (`email_verified: true`) removes the
password of a sign-up that is not verified. With `password_reset`, `POST
/auth/password-reset` sends a reset link with a signed token, and gives
202 also for an unknown user name. `POST /auth/password-reset/confirm`
sets the new password. A used or an ended token gives 400. The
extension file `app/core/messages_ext.py` delivers the messages of both
kinds: its stub writes the link to the log with
`ENVIRONMENT=development`, and gives 501 in production. The subject and
the text of a message are in the language of the request. With
`providers`, `GET /auth/providers/<name>/start` sends the browser to the
provider (the authorization code flow with PKCE), and `GET
/auth/providers/<name>/callback` checks the ID token (the signature
with the keys of the provider, the issuer, the audience, the end time,
and the nonce) and gives a bearer token. With `?return_to=<page>` of a
front end in `CORS_ORIGINS`, the callback sends the browser to the page
with the token in the fragment of the URL. The setting
`<NAME>_ISSUER` changes the issuer of a provider, for example for a
test provider. With `password: false`, the app has no
`POST /auth/sign-in`, no `PUT /auth/password`, no table of the password
hashes, and no `app.cli`. The Next.js app has the page `/sign-in` and a
session cookie, and its seed gives each user the password in
`SEED_PASSWORD`. Both need `AUTH_SECRET`. The React app (mock data)
accepts each mock user with the password `password`. Each front end has
a sign-out button in the top bar.

With `sign_up`, each front end has the public page `/sign-up`, and the
sign-in page links to it. The form asks for the fields in `fields`,
with the widgets and the checks of the entity fields, and for a
password. The Next.js app adds the user and its password in one
transaction, and starts the session. The React app with
`x-react-data: api` calls `POST /auth/sign-up`. The React app with mock
data keeps a new user only in the browser tab.

With `verify_email`, the sign-up of the Next.js app and of the React app
with `x-react-data: api` shows a message instead of the start page: the
new user opens the link in the message first. The public page
`/verify-email` is the page of the link: a button confirms the address,
so that a program that opens the links of a message does not confirm
it. After a sign-in with the correct password of an unverified user, the
sign-in page shows a button that sends a new link. The Next.js app uses
the same token rules as the FastAPI app, and the link starts with
`PUBLIC_URL`. Its extension file `src/shared/auth/messages.ext.ts`
(`deliverMessage`) delivers the messages of the verification and of the
password reset, with the stub of the FastAPI app. The React app calls
the endpoints of the FastAPI app: set `EMAIL_VERIFY_URL` to its page
`/verify-email`. The React app with mock data has no verification: the
sign-up signs in at once.

With `password_reset`, the Next.js app and the React app with
`x-react-data: api` have the public pages `/forgot-password` (it asks
for a reset link) and `/reset-password` (the page of the link: it sets a
new password), and the sign-in page links to the first one. The React
app calls the endpoints of the FastAPI app: set `PASSWORD_RESET_URL` to
its page `/reset-password`. The Next.js app uses the same token rules
as the FastAPI app, and the link starts with `PUBLIC_URL`. Its
extension file `src/shared/auth/messages.ext.ts` delivers the link,
with the same stub. The React app with mock data has no reset pages.

With `providers`, the sign-in page of each front end has a button for
each provider, with its `title`. With `password: false`, the page has
no password form. The Next.js app does the flow itself: the routes
`/auth/providers/<name>/start` and `/auth/providers/<name>/callback` do
the authorization code flow with PKCE, check the ID token with the
package `jose`, and set the session cookie. Register the redirect URI
`<PUBLIC_URL>/auth/providers/<name>/callback` at the provider, and set
`PUBLIC_URL` and the client variables. The React app with
`x-react-data: api` sends the browser to the flow of the FastAPI app,
with `return_to` set to its page `/auth/callback`: add the origin of
the React app to `CORS_ORIGINS` of the FastAPI app. The React app with
mock data signs in a mock user at once, as a demonstration. A failed
sign-in opens the sign-in page with a message.

## access

The optional `access` section gives each user a role, and each role the
operations and pages that it may use ([ADR 0012](adr/0012-access.md)).
It needs `auth`.

```yaml
# example: room-booking
access:
  role_field: role
  roles:
    admin:
      label: Admin
      operations: ["*"]
      pages: ["*"]
    member:
      label: Member
      operations: [list_bookings, read_booking, create_booking]
      pages: [bookings, booking_detail]
      records:
        Booking: { owner: organizer, operations: [read, change] }
```

- `role_field` is an `enum` field of the user entity. Each key of
  `roles` is a value of that field.
- `operations` and `pages` name the operations and pages of the role.
  `*` stands for all of them.
- The public operations and pages of `auth` stay open to all users. A
  user without a role, or with a role that is not in `roles`, may use
  only the public parts.
- `records` gives the role owner rules ([ADR 0018](adr/0018-owner-rules.md)):
  for each entity, the role uses only the records that its user owns.
  `owner` is a many-to-one relation of the entity to the user entity.
  `operations` is `read` (the lists and the reads), `change` (the
  creates, the changes, the deletes, and the custom operations), or both
  (the default). A rule for `read` also applies to the changes. All
  rules of an entity use the same relation. A rule does not apply to the
  public operations.

The FastAPI app gives 403 for an operation that the role may not call.
With an owner rule, a list gives only the records of the user, a read,
a change, a delete, or a custom operation on another record gives 404,
and a create sets the owner to the user.
The Next.js app shows "not found" for a page, and gives an error for a
server action. The React app (mock data) does the same checks in the
browser, so they are a demonstration, not a protection.
The menus, the page search, the links, and the actions of the front
ends show only the pages and the operations that the role allows. A
group of a menu without an allowed page does not show.
The front ends apply the owner rules too. The server actions of the
Next.js app use only the records of the user, and a detail page of a
record of another user shows "not found". The React app shows the
records that the FastAPI app gives, and with mock data the mock store
applies the rules in the browser, as a demonstration. For a user of an
owner rule, the create and update forms do not show the owner field,
and a new record belongs to the user.

## translations

The optional `translations` section gives the UI text in more than one
language. The text of the definition (titles, labels, messages) is in
the `default` language. Each other language translates the texts that
the app shows:

```yaml
translations:
  default: en
  languages:
    en: { label: English }
    de:
      label: Deutsch
      locale: de-DE
      text:
        Projects: Projekte
        New project: Neues Projekt
        Done: Erledigt
```

- `default` is a key of `languages`. The default language has no `text`.
- `label` is the name of the language in the language itself. The
  language switch of the app shows it.
- `locale` is a language tag (BCP 47), for example `de-CH` or
  `ar-EG-u-nu-latn`. It gives the format of the dates and numbers, the
  first day of the week, and the names of the months and days. The
  default is the code of the language, so the code must be a language
  tag when the language has no `locale`. `appgen validate` reports a
  locale that is not a language tag (`translation-locale`).
- `direction` is the direction of the text: `ltr` (left to right) or
  `rtl` (right to left). The default comes from the locale: a script
  subtag first (`az-Arab` is `rtl`, `ur-Latn` is `ltr`), else the
  language. The languages `ar`, `arc`, `azb`, `ckb`, `dv`, `fa`, `he`,
  `iw`, `ks`, `lrc`, `mzn`, `nqo`, `ps`, `sd`, `syr`, `ug`, `ur`, and
  `yi` are `rtl`. For example, `ar: { label: العربية, text: ... }` is
  `rtl` without `direction`.
- `text` maps a text of the default language, as the app shows it, to
  its translation. A key can be a text that the definition does not
  give, for example the default label of a field (`Due date` for
  `due_date`) or a default text of a form (`Cancel`, `Save`, `Create`).
- Each language translates the same keys. `appgen validate` reports a
  key that one language has and another language does not have
  (`missing-translation`).
- A text can hold values that the app fills in, in braces, for example
  `Page {page} of {count}`. The translation keeps each value, and can
  change their order: `Page {page} of {count}: Seite {page} von {count}`.
  `appgen validate` reports a translation that does not have the values
  of its key (`translation-values`).

The React and Next.js apps have a language switch in the top bar (and
in the frame of the pages without a layout). The React app keeps the
selected language in the browser storage. The Next.js app keeps it in
the cookie `<app name>-language`, and its server renders the pages, the
page titles, and the messages of the server actions in it. Without the
cookie, the server takes the first language of the `Accept-Language`
header that the app has, by its code or its locale, also with only the
same primary language (`de-CH` gives `de`), else the default language.
A text without a translation shows in the default language. The front
ends translate each text that they show: the titles, labels, and
descriptions of pages, menus, views, forms, and
dashboards, the badge labels, the option labels, the actions, the
messages of the form rules, the default texts of the generator, and the
fixed texts of the components (see the list below). The dates and
numbers have the format of the locale of the selected language: the
views, the forms, the filters, the charts, the date pickers, and the
calendars. The format of a field (`number`, `currency`, `percent`,
`date`, `datetime`, `relative_time`) and its currency stay the same in
each language. The `lang` of the page is the locale, and the `dir` of the
page is the direction of the language.

In a language from right to left, the front ends show the layout from
right to left: the sidebar, the menus, the forms, the tables, and the
date pickers. The start of a line is at the right, so the sidebar with
`side: left` shows at the right, and a column with `align: end` at the
left. The icons of a direction, for example the arrows of the pages of a
list and of the breadcrumbs, turn. The icons of the definition do not
turn.

The FastAPI app gives its messages in the language of the request: the
first language of the `Accept-Language` header that the app has, as the
Next.js server takes it, else the default language. Each response has
the locale in `Content-Language`. The title and the detail of the
problem details, and the message of each error of the input, are in the
language (see the list below). With `x-react-data: api`, the API client
of the React app sends the locale of the selected language.

### Fixed texts

The components of the front ends show these texts in the default
language. Add a key to translate one. A text that a component does not
use in the app does not show.

- App shell: `Search pages`, `Ctrl K`, `Find a page by its title.`,
  `Type a page title`, `No page has this title.`, `Pages`, `Suggestions`,
  `Language`, `Switch the color mode`, `Light`, `Dark`, `System`,
  `Toggle Sidebar`, `Sidebar`, `Displays the mobile sidebar.`,
  `breadcrumb`, `More`, `Notifications`, `Close toast`, `Sign in`,
  `Password`, `Sign out`, `Sign up`, `Do you need an account?`,
  `Do you have an account?`.
- The sign-in with a provider: `or`,
  `No user has this user name. Ask an administrator.`,
  `The sign-in with the provider failed.`.
- The password reset: `Did you forget the password?`,
  `Reset the password`,
  `Enter your user name. The app sends you a link to set a new password.`,
  `Send the link`,
  `If the user name exists, the user gets a message with a reset link.`,
  `Go to the sign-in`, `Set a new password`, `New password`,
  `Set the password`,
  `The password is changed. Sign in with the new password.`,
  `The reset link is not valid, was used, or has ended.`,
  `The request failed.`.
- The verification of the email address:
  `Open the link in the message to confirm the email address.`,
  `Confirm the email address first: open the link in the message.`,
  `Send the link again`,
  `If the user name needs a confirmation, the user gets a message with a link.`,
  `Confirm the email address`,
  `Confirm that the email address of the new account is yours.`,
  `The email address is confirmed. Sign in with your password.`,
  `The link is not valid, or has ended.`.
- The messages to the users of the Next.js app (the subject is the
  title of the app and a text): `Reset the password`,
  `Open the link to set a new password. The link is valid one time.`,
  `If you did not ask for a new password, ignore this message.`,
  `Confirm the email address`,
  `Open the link to confirm the email address of your new account.`,
  `If you did not make an account, ignore this message.`.
- The page of an unknown path and the stubs of the generation gaps:
  `This page does not exist`, `Make sure that the address is correct.`,
  `Go to the start page`, `Not available yet.`,
  `Not implemented yet: {element}`.
- Lists: `Rows per page`, `{first}–{last} of {total}`,
  `Page {page} of {count}`, `First page`, `Previous page`, `Next page`,
  `Last page`, `pagination`, `Go to previous page`, `Go to next page`,
  `Previous`, `Next`, `More pages`, `Select all`, `Select the row`,
  `Actions`, `{count} selected`, `Clear the selection`, `Loading`,
  `Try again`, `Yes`, `No`.
- Filters: `No matching records`, `Change or reset the filters.`,
  `Reset the filters`, `Reset`, `{label}: all`, `{count} chosen`,
  `No value has this name.`, `Clear the filter`, `Clear {label}`.
- Boards and calendars: `Move to`, `Drop a card here`,
  `The column has more than {limit} cards.`, `The card did not move.`,
  `Show more` (a board of the API client),
  `Previous week`, `Next week`, `Previous month`, `Next month`, `Today`,
  `Calendar mode`, `Week`, `Month`.
- Date pickers: `Navigation bar`, `Go to the next month`,
  `Go to the previous month`, `Choose the month`, `Choose the year`,
  `Today, {date}`, `{date}, selected`.
- Dashboards: `View all`, `No data yet`, `Other`, `None`.
- Actions and forms: `Cancel`, `Close`, `Saved.`,
  `The action did not succeed.`, `The form did not save.`,
  `Select a value`, `Search`, `No results.`, `Loading…` (a search on
  the server), `Select a record`,
  `Select records`, `Clear`, `Remove {label}`, `Pick a date`, `Time`,
  `Command Palette`, `Search for a command to run...`.
- The messages of the form fields: `Enter a value.`, `Select a value.`,
  `Enter a whole number.`, `Enter a valid email address.`,
  `Enter a valid URL.`, `Use the correct format.`,
  `Use {count} or more characters.`, `Use {count} or fewer characters.`,
  `Use {count} or more.`, `Use {count} or less.`.
- The messages of the data access and the sign-in (the mock data and
  the API client of the React app, and the server actions of the Next.js
  app): `The state of {entity} cannot change from {before} to {after}.`,
  `A new {entity} starts with the state {initial}, not {state}.`,
  `{entity} {id} does not exist.`, `The API gave the status {status}.`,
  `The input is not valid.`, `The server could not do the operation.`,
  `The record refers to a record that does not exist, or other records refer to it.`,
  `Another record has the same value, and the value must be unique.`,
  `Sign in to do this.`, `Your role may not do this operation.`,
  `The sign-in failed.`, `The user name or the password is not correct.`,
  `The browser does not keep the session.`,
  `A user with this user name exists.`.
- The rate limit of the Next.js app:
  `Send not more than {limit} requests in each minute.`, and with the
  store in Redis
  `The store of the rate limit is not available. Try again later.`.

### Messages of the FastAPI app

The FastAPI app gives these messages in the default language. Add a key
to translate one. The rules and the workflows give their own messages.

- The titles of the problem details: `Bad Request`, `Unauthorized`,
  `Forbidden`, `Not Found`, `Method Not Allowed`, `Conflict`,
  `Unprocessable Content`, `Too Many Requests`, `Internal Server Error`,
  `Not Implemented`, `Bad Gateway`, `Service Unavailable`.
- The errors of the input: `The request is not valid.`, and for each
  value `Enter a value.`, `Use {count} or more characters.`,
  `Use {count} or fewer characters.`, `Use {count} or more.`,
  `Use {count} or less.`, `Enter a whole number.`, `Enter a number.`,
  `Use the correct format.`, `Select a value.`, `Enter a valid URL.`,
  `Enter a valid email address.`, `The value is not valid.`. The `type`
  of the error keeps the kind of the error.
- The data access: `No {entity} has the ID {id}.`,
  `The field '{field}' refers to {entity} {id}, which does not exist.`,
  `The field '{field}' refers to {entity} records that do not exist: {ids}.`,
  `The change breaks a rule of the data: a value must be unique, or other records refer to this record.`,
  `Cannot sort by '{name}'. Use one of: {names}.`.
- The workflows without a message:
  `A new record starts with the {field} '{initial}', not '{state}'.`,
  `The {field} cannot change from '{before}' to '{after}'.`.
- The sign-in and the access checks: `Sign in to use this endpoint.`,
  `The user name or the password is not correct.`,
  `The current password is not correct.`,
  `Your role may not do this operation.`, `The server has no AUTH_SECRET.`,
  `If the user name exists, the user gets a message with a reset link.`,
  `The reset link is not valid, was used, or has ended.`.
- The verification of the email address:
  `Open the link in the message to confirm the email address.`,
  `Confirm the email address first: open the link in the message.`,
  `If the user name needs a confirmation, the user gets a message with a link.`,
  `The link is not valid, or has ended.`.
- The messages to the users (the subject is the title of the app and a
  text): `Reset the password`,
  `Open the link to set a new password. The link is valid one time.`,
  `If you did not ask for a new password, ignore this message.`,
  `Confirm the email address`,
  `Open the link to confirm the email address of your new account.`,
  `If you did not make an account, ignore this message.`.
- The sign-in with a provider:
  `The server has no client ID or client secret for {name}.`,
  `The provider did not answer correctly: {url}`,
  `The discovery document of the provider is not valid.`,
  `The discovery document of the provider has another issuer.`,
  `The token endpoint of the provider did not answer.`,
  `The provider did not accept the code. Start the sign-in again.`,
  `The token endpoint of the provider gave no ID token.`,
  `The ID token is not valid: the provider has no key for it.`,
  `The ID token is not valid: {error}`,
  `The ID token is not valid: the nonce is not the one of the flow.`,
  `The ID token has no claim '{claim}'.`,
  `The provider did not verify the email address.`,
  `No user has the user name {username}. Ask an administrator.`,
  `The claims of the provider do not give a valid user.`,
  `The origin of return_to is not in CORS_ORIGINS.`,
  `The provider gave the error '{error}'.`,
  `The state of the callback is not correct. Sign in again.`,
  `The sign-in has no valid flow. Sign in again.`, `The sign-in failed.`.
- The rate limit: `Send not more than {limit} requests in each minute.`,
  and with the store in Redis
  `The store of the rate limit is not available. Try again later.`.
- The endpoints of the exposed APIs:
  `The API {api} answered with the status {status}.`,
  `The API {api} gave no valid answer.`.

## Extension keys

A key that starts with `x-` is an extension key, as in OpenAPI. The
root and each element can have them. The DSL keeps them and does not
check them. A binding can read them, for example the React binding
reads `x-mock-count` on an entity (the number of mock records). A
binding declares a schema for the keys that it reads, so `appgen
validate` and `appgen generate` report a wrong key or value of a binding
in use ([bindings.md](bindings.md#extension-keys)). Any other unknown key
is an error.

## Reserved sections

No top-level key is reserved now. The sections that
[ADR 0002](adr/0002-app-definition-dsl-v0.md#how-the-out-of-scope-features-fit-in-later)
reserved (`auth` and `access`) are optional sections. A new section of
a later version is optional too, so that the definitions that exist
stay valid.

## Validation

`appgen validate <file>` checks the YAML syntax, the keys and values
against the schema, the names, and the references between elements
(for example a relation to an entity that does not exist, a token loop,
or a view field of the wrong type). It also reads the OpenAPI document of
each API, and checks its operations and its security scheme. It reads the
data files of the seed, and checks the values of the seed records. Each
diagnostic has a code, a message, and the line and the column. `--format json` writes the
diagnostics as JSON. `examples/invalid/` has one broken definition for
each diagnostic code. `appgen generate` validates the definition first,
and writes no file if it is not valid.
