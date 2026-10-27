<!-- Made from docs/dsl.md by scripts/update_skill_references.py. Do not edit. -->

# App definition reference

An app definition is one YAML file that describes an application: its
data model, its operations, its pages, and its UI. appgen validates the
file and generates the code of an app from it, for one binding (a target
stack). This page is the reference for each section of the file, with
examples. [ADR 0002](https://github.com/ds411/app-generator/blob/main/docs/adr/0002-app-definition-dsl-v0.md) and
[ADR 0003](https://github.com/ds411/app-generator/blob/main/docs/adr/0003-ui-dsl.md) give the reasons for the design.
[`examples/project-tracker/app.yaml`](https://github.com/ds411/app-generator/blob/main/examples/project-tracker/app.yaml) is a complete example.

Most examples on this page are parts of a definition, and come from
[`examples/project-tracker/app.yaml`](https://github.com/ds411/app-generator/blob/main/examples/project-tracker/app.yaml). A comment on the first lines of an
example tells where it goes: `# in: entities.Task` is the place of the
example in a definition (the default is the top level), and
`# example: room-booking` names the example that it comes from
([`examples/room-booking/app.yaml`](https://github.com/ds411/app-generator/blob/main/examples/room-booking/app.yaml)). `tests/test_docs.py` puts each
example into its example definition, and checks that the result is
valid.

## Contents

- [The file](#the-file)
- [Names and IDs](#names-and-ids)
- [app](#app)
- [entities](#entities)
- [seed](#seed)
- [storage](#storage)
- [operations](#operations)
- [pages](#pages)
- [workflows](#workflows)
- [jobs](#jobs)
- [notifications](#notifications)
- [apis](#apis)
- [webhooks](#webhooks)
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
  - [The signed-in user](#the-signed-in-user)
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
| `webhooks`   | No       | The endpoints that other systems send signed events to.       |
| `seed`       | No       | The records that the apps start with, for each entity.        |
| `storage`    | No       | The place of the files of the `file` and `image` fields.      |
| `jobs`       | No       | Work on a schedule, or at the time of a date field of each record. |
| `notifications` | No    | The notices that users get when a record that concerns them changes. |

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
| Field, relation, param, operation, page, enum value, API, webhook, UI element | `^[a-z][a-z0-9_]*$` | `due_date` |
| Operation of an API (its operation ID)   | `^[A-Za-z_][A-Za-z0-9_]*$` | `getPublicHolidays` |
| Seed record key                          | `^[A-Za-z0-9_]+$`     | `a101`, `hq`      |
| Token and token group                    | `^[a-z0-9][a-z0-9_]*$` | `600`, `primary` |
| Icon (a [Lucide](https://lucide.dev) name) | `^[a-z][a-z0-9-]*$` | `folder-kanban`   |

`id` is reserved: each entity has an implicit primary key `id` of type
`uuid`.

Each element has an **ID**: the mapping keys from the root to the
element, with dots. Traces in the generated code refer to elements by
ID ([traces.md](https://github.com/ds411/app-generator/blob/main/docs/traces.md)).

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
| Storage      | `storage`                                  |
| Webhook      | `webhooks.commits`                         |
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
| `events`        | No       | Custom operations that run after a record is created, changed, or deleted (see [Events](#events)). |
| `history`       | No       | The change log of the records: `true`, or a mapping (see [History](#history)). |
| `live`          | No       | The live updates of the records in the open views: `true`, or a mapping (see [Live updates](#live-updates)). |

### The CRUD shorthand

`crud` asks for the CRUD operations of an entity, and optionally for a
default table view, detail view, and forms. The loader expands it
before validation ([ADR 0008](https://github.com/ds411/app-generator/blob/main/docs/adr/0008-crud-shorthand.md)). The names
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
The detail view of an entity with [`history`](#history) also has the
tab `history`, with the change log of the record.

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
| `text`     | Long text with line breaks.          | `min_length`, `max_length`, `mentions` |
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
| `file`     | One file, for example a PDF.         | `max_size`, `types`                   |
| `image`    | One image, for example a photo.      | `max_size`, `types`                   |
| `point`    | A place: a latitude and a longitude. |                                       |

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

`currency_field` gives each record its own currency: the field path of
a `string` or an `enum` field with the ISO 4217 code, for example
`customer.currency` for the invoices of a customer. The values of an
`enum` field are the codes in lower case, for example `[usd, eur]`. The
views show each amount in the currency of its record, and load the
related records of the path. A form uses the currency field of the form,
the record that it edits, or the record of a relation field of the form
(one relation). Else, and for a record without a code, the amount has
the currency of `currency`. A `sum`, `avg`, `min`, or `max` of such a
field in a dashboard widget needs one currency (see
[dashboards](#dashboards)).

`translatable: true` gives a `string` or `text` field a value in each
language of `translations` (see
[Values in each language](#values-in-each-language)).

The `file` and `image` fields hold a file (see [File fields](#file-fields)).
A `point` field holds a place on the earth (see [Point fields](#point-fields)).

`mentions: true` lets a `text` field mention users with `@` (see
[Mentions](#mentions)).

`sequence` gives a `string` or an `integer` field the next number of a
sequence (see [Sequence numbers](#sequence-numbers)).

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

```yaml
# in: entities
Customer:
  fields:
    name: { type: string, required: true }
    currency: { type: enum, values: [usd, eur, gbp], default: usd }
Invoice:
  fields:
    total: { type: decimal, format: currency, currency_field: customer.currency }
  relations:
    customer: { kind: many_to_one, target: Customer, required: true }
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
| `count(relation)`    | `count(lines)`                  | The number of related records.                  |
| `sum(relation.field)` | `sum(lines.amount)`            | The sum of a field of the related records.      |
| `avg`, `min`, `max`  | `max(lines.amount)`             | The average, the smallest, and the largest value of a field of the related records. |

An empty operand, or a division by zero, gives an empty value. The apps
round a `decimal` field to its `scale`, and an `integer` field to a
whole number. The FastAPI app returns the value in the read schema (a
property of the model), and the front ends compute it in the views.

A total (`count`, `sum`, `avg`, `min`, or `max`) uses the related
records of a `one_to_many` or a `many_to_many` relation of the entity
([ADR 0034](https://github.com/ds411/app-generator/blob/main/docs/adr/0034-totals.md)). The field of a total is a stored
`integer` or `decimal` field of the related entity, one step away: not
a computed field, and not a field of a record further away. The total
of no records is 0 for `count` and `sum`, and empty for `avg`, `min`,
and `max`.

`filter` selects the related records of all totals of the expression.
It is the filter of the [dashboards](#dashboards): stored fields of the
related entity, each with a value or with operators, but without
`$today` and `$now`. A `many_to_one` relation of the related entity to
the user entity takes only `$me`, the signed-in user (see
[The signed-in user](#the-signed-in-user)), for example the unread
messages of the user. A field without totals takes no `filter`.

```yaml
# in: entities
Invoice:
  fields:
    discount: { type: decimal, min: 0, scale: 2, default: 0 }
    line_count: { type: integer, computed: count(lines) }
    total: { type: decimal, scale: 2, computed: sum(lines.amount) - discount }
    largest_line: { type: decimal, scale: 2, computed: max(lines.amount) }
    credits:
      type: decimal
      scale: 2
      computed: sum(lines.amount)
      filter: { kind: credit }
  relations:
    lines: { kind: one_to_many, target: InvoiceLine, inverse: invoice }
InvoiceLine:
  fields:
    amount: { type: decimal, required: true, scale: 2 }
    kind: { type: enum, values: [charge, credit], default: charge }
  relations:
    invoice: { kind: many_to_one, target: Invoice, required: true, inverse: lines }
```

The FastAPI app computes each total in the database, with a subquery in
each read and list query of the entity. When the expression has only
totals, numbers, stored number fields of the entity, `+`, `-`, and `*`,
the list endpoint can sort by the field, and filter it with the
parameters `<field>_min` and `<field>_max`. The Next.js app computes
the totals in the database too, and the React app from its mock data,
or it reads the value from the FastAPI app.

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

### Sequence numbers

A field with `sequence` gets the next number of a sequence when the app
creates a record, for example the number `INV-1001` of an invoice. Each
field with `sequence` has its own sequence. The forms do not show the
field, and the create and the change do not take a value of it.

| Option   | Meaning                                                    | Default |
| -------- | ---------------------------------------------------------- | ------- |
| `start`  | The first number, from 1.                                  | `1`     |
| `prefix` | The text before the number: letters, digits, and `._/#-`. Only for a `string` field. | none |
| `width`  | The smallest number of digits: zeros go before a shorter number. Only for a `string` field. | none |

A field with `sequence` is a `string` or an `integer` field. It cannot
have `required`, `default`, `computed`, `translatable`, or the rules of
a value (`pattern`, `min_length`, `max_length`, `min`, `max`): the
record always has a value, and the database gives it. `unique: true`
lets the database reject a second record with the same number, for
example after a manual change of a number in the database. A seed
record does not give a value of the field: the seed records get the
numbers in their order, from `start`.

The apps take the numbers as follows:

- The Next.js app and the FastAPI app on PostgreSQL take the number
  from a database sequence. A database sequence does not go back: a
  create that fails after it takes a number (for example because of a
  rule of the record) skips that number. The numbers are in order, but
  there can be holes.
- The FastAPI app on SQLite (the tests and the local development) has
  no sequences: it takes the largest number of the table plus one.
- The React app without an API gives the numbers in order to the mock
  records, and the mock store gives the next number to a new record.

```yaml
# in: entities
Invoice:
  display_field: number
  fields:
    number:
      type: string
      unique: true
      sequence: { start: 1001, prefix: INV-, width: 4 }
    issued_on: { type: date, required: true }
```

### File fields

A `file` or an `image` field holds one file of a record, for example the
screenshot of a task or the photo of a product
([ADR 0027](https://github.com/ds411/app-generator/blob/main/docs/adr/0027-files.md)). The apps keep the file in the place of
the [storage](#storage) section, and the record keeps the name, the
size, and the media type of the file. An `image` field is a `file` field
that allows only images.

| Option     | Content                                                                 |
| ---------- | ----------------------------------------------------------------------- |
| `max_size` | The largest file: a number of bytes, or a number with `B`, `KB`, `MB`, or `GB`, for example `5MB`. 1 KB is 1024 bytes. The default is `10MB`. |
| `types`    | The media types that the field allows, for example `application/pdf`, or all types of a group, for example `image/*`. The default of a `file` field is all types, and of an `image` field `image/png`, `image/jpeg`, `image/gif`, and `image/webp`. |

```yaml
storage: { kind: local }
entities:
  Task:
    fields:
      screenshot: { type: image, max_size: 5MB }
      report: { type: file, max_size: 20MB, types: [application/pdf, "text/*"] }
```

- A definition with a file field needs the section `storage`.
- The apps upload a file after they create the record, so a file field
  takes no `required`, `unique`, or `default`. A form can require a file
  with the rule `required` of its form field.
- A file field cannot be computed, and a computed field, an entity rule,
  a sort, or a filter cannot use it. A param of an operation cannot be a
  file.
- For more files of one record, use a `one_to_many` relation to an
  entity with a file field, for example `Attachment`.

The FastAPI app keeps the file of a record in a JSON column, and has
these endpoints for each file field:

- `PUT <path>/{id}/<field>` uploads the file, with a multipart body that
  has the file in the part `file`, and returns the record. A new file
  replaces the old one. `DELETE <path>/{id}/<field>` deletes the file.
  The operation IDs are `upload_<entity>_<field>` and
  `delete_<entity>_<field>`, for example `upload_task_screenshot`.
- The endpoints need the permission of the update operation of the
  entity, else of its create operation, and the record rules of a change
  apply. An entity without both has no endpoints for its files: only
  the seed gives them.
- A file that is larger than `max_size` gives 413, and a type that the
  field does not allow gives 415. The app takes the type from the first
  bytes of a PNG, JPEG, GIF, WebP, or PDF file, else from the part.
- A read gives the file as `name`, `size`, `type` (the media type), and
  `url`. The URL is a signed link to the app (`/file-links/<token>`) that
  works without a sign-in, so that an `<img src>` shows the image. It
  ends after `STORAGE_LINK_SECONDS`.
- The delete of a record deletes its files. The files of the records
  that the database deletes with `on_delete: cascade` stay in the
  storage.
- A seed record with a file gets the file in the storage when the seed
  adds the record.

The Next.js app keeps the file of a record in a `jsonb` column too:

- The server actions `upload<Entity>FileAction` and
  `remove<Entity>FileAction` of each entity with file fields take the
  name of the field, and the file in a form data. The data access
  `<entity>Files` calls them (`upload(id, field, file)` and
  `remove(id, field)`). They need the permission of the update operation
  of the entity, else of its create operation, and the record rules of a
  change apply.
- A file that is larger than `max_size`, or a type that the field does
  not allow, gives a validation error. `next.config.ts` allows server
  action bodies of the largest file and 1 MB more.
- A record gives the file as `name`, `size`, `type`, and `url`. The URL
  is the route `/files/<entity>/<id>/<field>`, which checks the session
  and the access rules of a read of the record. So no page path of a
  definition with `storage` can start with `/files/`.
- The delete of a record and the seed work as in the FastAPI app.

The front ends (React and Next.js) show and upload the files:

- A form field of a file field gets the widget `file`: a drop zone and a
  button that opens the file dialog, with the current file, a preview of
  an image, and a button that removes the file. The form checks the size
  and the type of the new file. It saves the record first, and then
  uploads the new files and deletes the removed files with
  `<entity>Files`. The create and the update operations take no file.
- A view shows an `image` field as an image: small in a table column,
  large in a detail section. It shows a `file` field as a link with the
  name and the size of the file. The format `avatar` shows an image in a
  circle, with the initials of the record when it has no image. The
  format `text` shows the name of the file. A view does not sort by a
  file field.
- A card of a `cards` view can show an `image` field at its top (`image`).
- The React app with mock data keeps a new file in the browser (an object
  URL) until the page loads again. Its seed files are `data:` URLs in the
  mock data. With the data source `api`, it sends the files to the
  endpoints of the FastAPI app.
- The sign-up form cannot ask for a file field.

### Point fields

A `point` field holds a place on the earth: a latitude and a longitude
in degrees (WGS 84), for example the place of a listing
([ADR 0046](https://github.com/ds411/app-generator/blob/main/docs/adr/0046-geo-points.md)). The value is a mapping with `lat`
(from -90 to 90) and `lng` (from -180 to 180), for example
`{lat: 38.7223, lng: -9.1393}`. A seed record also takes the text
`<lat>,<lng>`, for example `"38.7223,-9.1393"` in a CSV data file.

```yaml
entities:
  Site:
    display_field: name
    crud: [list]
    fields:
      name: { type: string, required: true }
      location: { type: point, required: true, label: Location }
ui:
  views:
    site_table:
      kind: table
      entity: Site
      columns: { name: {} }
      filters:
        nearby: { kind: near, field: location, label: Near, distance: 5 }
        in_map: { kind: area, field: location }
```

- A point field takes `required`, `label`, `description`, and a
  `default` point. It takes no `unique`, and it cannot be computed.
- The apps keep a point in two columns of numbers, `<field>_lat` and
  `<field>_lng`, with an index of the two columns. They need no PostGIS,
  so that the FastAPI tests run on SQLite. No other field or relation of
  the entity can have the name of one of the two columns.
- An entity rule, a sort, and the `filter` of a dashboard widget or of a
  job cannot use a point field. The list views filter the points with
  the filters `near` and `area` (see [views](#views)).
- A point field cannot be the `display_field`, a field or a value of a
  notification, or a field of the sign-up form. The param of an
  operation cannot be a point: use two `decimal` params.
- A view shows a point as its latitude and its longitude, for example
  `38.7223, -9.1393`, and a map view shows the records on a map (see
  [views](#views)). The form widget `point` has an input for the
  latitude and one for the longitude. A column of a lines editor cannot
  be a point.
- A form field of a point field gets the widget `point`.
- The FastAPI app gives a point as an object with `lat` and `lng`
  (the schema `GeoPoint`), and gives 422 for a latitude or a longitude
  out of its range. The change log keeps a point as an object too.
- The React and Next.js apps do not generate point fields yet: they stop
  with an error.

### Entity rules

`rules` is a mapping from rule name to rule. A rule checks more than
one field of a record, or more than one record. The back ends (FastAPI
and Next.js) check the rules when they create or change a record. The
React app has mock data and no back end, so it does not check them.

| `kind`       | Keys                                   | Check                                         | Error |
| ------------ | -------------------------------------- | --------------------------------------------- | ----- |
| `compare`    | `field`, `op`, `other`, `message`      | `field op other`. `op` is `eq`, `ne`, `lt`, `lte`, `gt`, or `gte`. `field` and `other` are fields or totals of the lines. | 422 |
| `unique`     | `fields` (two or more), `message`      | No two records have the same values. The table has a unique constraint. | 409 |
| `no_overlap` | `start`, `end`, `scope`, `message`     | The ranges `[start, end)` of two records with the same `scope` values do not overlap. | 409 |

The fields of a rule are stored fields of the entity. `unique` and
`scope` also take `many_to_one` and `one_to_one` relations (their
foreign keys). A compare rule compares two numbers, two dates, two
date-times, or two texts. The start and the end of a `no_overlap` rule
are two `date` or two `datetime` fields. An empty value passes a
compare rule and a `no_overlap` rule: `required` checks it. The mock
data keeps the compare and the unique rules. The `available` filter of a
view keeps the records without a related record in the picked days of a
`no_overlap` rule (see [views](#views)).

A side of a compare rule can also be a total of the lines of the
record, as in a [computed field](#computed-fields): `count(<relation>)`,
or `sum`, `avg`, `min`, or `max` of `<relation>.<field>`, through a
`one_to_many` relation ([ADR 0034](https://github.com/ds411/app-generator/blob/main/docs/adr/0034-totals.md)). A `count`
compares with an `integer`, and the other totals with a number. The
FastAPI and the Next.js apps check such a rule after each create and
update of the record, with the totals in the database. An operation
with [`lines`](#operations) checks it after it writes the lines, in the
same transaction, so a broken rule stores nothing. The count and the
sum of no lines are 0, and the other totals of no lines are empty, so
they pass.

```yaml
# in: entities.Project
rules:
  within_budget:
    kind: compare
    field: sum(budget_lines.amount)
    op: lte
    other: budget
    message: The budget lines must stay within the budget.
```

- A change of a line through the operations of the lines does not
  check the rules of its record. Write the lines with an operation of
  the record that has `lines`.
- The seed records keep the rule with their seed lines. The mock data
  does not keep a rule with totals.

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

### Events

`events` maps a change of a record to a custom operation of the entity
([ADR 0031](https://github.com/ds411/app-generator/blob/main/docs/adr/0031-events.md)). The app runs the operation after the
change is in the database, in the transaction of the change, with the
record. An error of the operation rolls back the change and the
work of the operation.

| Event     | The operation runs                                              |
| --------- | --------------------------------------------------------------- |
| `created` | After a new record is stored.                                   |
| `changed` | After an update gives a new value to a stored field, or to one of `fields`. |
| `deleted` | After a record is deleted. The operation gets the deleted record. |

An event is the name of the operation, or a mapping with `operation`,
`fields` (only for `changed`: the stored fields that the event
watches), and `description`. A transition of a workflow can also run an
operation (`run`, see [workflows](#workflows)).

```yaml
# example: room-booking
# in: entities
Booking:
  events:
    # A new time of a booking goes to the organizer.
    changed: { operation: notify_organizer, fields: [starts_at, ends_at] }
```

- The operation is a custom operation of the same entity. The apps run
  it without params, so each param of it is optional or has a default.
  It calls no API (`apis`): a transaction is not the place for a call to
  another service. Work that can wait belongs in a [job](#jobs).
- Until the operation has its logic (a generation gap), its stub fails,
  and so each change that starts the event fails.
- The data access functions of the apps run the events, so the
  generated operations and the custom operations both start them. A
  change in the operation of an event starts no other event: the events
  stop after one level. In the operation, a commit of a data access
  function does not commit: the change that started the event commits.
- A change outside these functions starts no event: SQL in a script, a
  record that the database deletes with `on_delete: cascade`, and the
  seed.
- The FastAPI app and the Next.js app run the events in their
  repositories. The mock store of the React app runs them after the
  change, as a demonstration: it has no transactions, so an error of the
  operation does not undo the change. With the FastAPI app
  (`x-react-data: api`), the FastAPI app runs them.

### History

`history` keeps a change log of the records of the entity
([ADR 0040](https://github.com/ds411/app-generator/blob/main/docs/adr/0040-history.md)). Each create, change, and delete of a
record adds an entry with the user, the time, and the old and the new
value of each field that changed. A restore gives the old values of an
entry back.

| Key           | Required | Content                                                         |
| ------------- | -------- | --------------------------------------------------------------- |
| `fields`      | No       | The fields and the relations that the log keeps. The default is all: the stored fields except the file fields, and the `many_to_one` relations. |
| `description` | No       | Text.                                                           |

`history: true` keeps all of them.

```yaml
# example: room-booking
# in: entities
Booking:
  # The change log keeps who changed the time, the room, and the state.
  history: { fields: [title, starts_at, ends_at, status, room] }
```

- An entry has the action `created`, `changed`, `deleted`, or
  `restored`, the signed-in user (none without a user, for example in a
  job), the time, and the changes: the old and the new value of each
  field, by the name in the definition. A relation has the ID of its
  target. A translatable field has the value of the default language.
- The data access functions of the apps add the entries in the
  transaction of the change, after the [events](#events). A change
  without a new value adds no entry. A change outside these functions
  adds none: SQL in a script, a record that the database deletes with
  `on_delete: cascade`, and the seed.
- A restore gives the fields of the entry of a change their old values
  back, and keeps the later changes of the other fields. It is a change,
  with the checks of a change: the rules, the workflows, the record
  rules, and the events. It adds an entry `restored`.
- The entries of a record need the access of the read operation of the
  entity, and a restore the access of its update operation. Without
  the operation, the app has no endpoint for them.
- The FastAPI app has the endpoints `GET /<entity>/{id}/history` (the
  entries, the newest first) and
  `POST /<entity>/{id}/history/{entry_id}/restore`. The entries stay
  after the delete of a record.
- The Next.js app keeps the same table, and its server actions add the
  entries. The React app with mock data keeps the entries in memory,
  until the page reloads, and the React app with the FastAPI app
  (`x-react-data: api`) reads them from the endpoints.
- A tab of a detail view with `history: true` shows the entries (see
  [views](#views)).

### Live updates

`live` sends the creates, the changes, and the deletes of the records
of the entity to the open views of the apps, so that a user sees the
changes of the other users at once
([ADR 0051](https://github.com/ds411/app-generator/blob/main/docs/adr/0051-live-updates.md)).

| Key           | Required | Content |
| ------------- | -------- | ------- |
| `description` | No       | Text.   |

`live: true` is the short form. The entity needs a list or a read
operation (the validator reports `missing-key`).

```yaml
# in: entities.Task
# The open views show the changes of the tasks at once.
live: true
```

- An event has the type (`created`, `changed`, or `deleted`), the
  entity, and the ID of the record, but no values: a view reads the
  record again with the operations of the entity. The event comes after
  the commit of the transaction. A transaction that rolls back gives no
  event.
- All the code that writes through the database sessions of the app
  gives the events: the generated and the custom operations, the
  [events](#events), the restores of the [history](#history), and the
  jobs. A change outside these sessions gives none: SQL in a script, a
  record that the database deletes with `on_delete: cascade`, and an
  `update` or a `delete` statement of many records.
- A user gets the events of an entity if the role of the user may call
  a list or a read operation of the entity. With a
  record rule ([access](#access)) for the reads, a user gets only the
  events of the records that the user may read before or after the
  change.
- The FastAPI app has the endpoint `GET /live`: a stream of
  server-sent events. The first event is `open`. The event `reset`
  tells the client to read its views again, for example after a loss of
  events. With Redis in the setting `LIVE_EVENTS_URL`, all replicas and
  the worker of the jobs send their changes to the streams of all
  replicas. Without it, each process sends only its own changes. With
  the sign-in, `POST /live/ticket` gives a short ticket for the stream,
  because the browser cannot send a bearer token with `EventSource`.
- The Next.js app has the same stream at `/api/live`, with the session
  cookie of the user and the same `LIVE_EVENTS_URL`. The React app with
  the FastAPI app (`x-react-data: api`) reads the stream of the FastAPI
  app. The React app with mock data has no stream.
- In the Next.js app and the React app, the open views of an entity
  load their data again after the events of the entity. The events of
  50 ms give one load.

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
([ADR 0021](https://github.com/ds411/app-generator/blob/main/docs/adr/0021-seed-data.md)):

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
  value. A computed field and a field with `sequence` take no value: the
  records get the numbers of the sequence in their order.
- Without a seed, an entity has generated mock records: 12, or the
  number of the extension key `x-mock-count`. With a seed, the entity has
  its seed records and `mock` generated records. A generated record can
  refer to a seed record.
- The React app has the seed records first in its mock data. The
  Next.js seed (`pnpm db:seed`) and the FastAPI seed (`uv run python -m
  app.cli seed`) add each seed record that the database does not have,
  by ID, and add generated records only if all tables are empty.

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
| `file`, `image`                            | The path of a local file, from the folder of the definition, for example `files/board.png`. |
| `point`                                    | A mapping `{lat: 38.7223, lng: -9.1393}`, or a text `<lat>,<lng>`. |

The file of a `file` or an `image` field must suit the `max_size` and
the `types` of its field, and have 1 MB or less: the apps keep the seed
files in their code. The extension of the file gives its media type:
`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.avif`, `.svg`, `.pdf`,
`.txt`, `.md`, `.csv`, `.json`, `.zip`, `.mp3`, `.mp4`, or `.webm`. The
output manifest records the hash of each file.

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

## storage

The optional `storage` section gives the place of the files of the
`file` and `image` fields ([ADR 0027](https://github.com/ds411/app-generator/blob/main/docs/adr/0027-files.md)). Each key that
ends with `_env` names the environment variable of a setting of the apps.

| Key              | Content                                                          |
| ---------------- | ---------------------------------------------------------------- |
| `kind`           | Required. `local` (a folder of the server) or `s3` (Amazon S3, or another service with the S3 API). |
| `folder_env`     | The variable of the folder. Default: `STORAGE_FOLDER`.           |
| `bucket_env`     | `s3` only. The variable of the bucket. Default: `STORAGE_BUCKET`. |
| `region_env`     | `s3` only. The variable of the region. Default: `STORAGE_REGION`. |
| `endpoint_env`   | `s3` only. The variable of the URL of a service with the S3 API, empty for Amazon S3. Default: `STORAGE_ENDPOINT`. |
| `access_key_env` | `s3` only. The variable of the access key ID. Default: `STORAGE_ACCESS_KEY_ID`. |
| `secret_key_env` | `s3` only. The variable of the secret access key. Default: `STORAGE_SECRET_ACCESS_KEY`. |

```yaml
storage:
  kind: s3
  bucket_env: FILES_BUCKET
```

With the kind `s3`, the apps keep the files in the folder while the
variable of the bucket has no value, for example on the machine of a
developer and in the tests. The default folder is `uploads`. A variable
cannot be a variable that the apps use for their own settings, or a
variable of an API. The variables of the keys cannot start with
`NEXT_PUBLIC_` or `VITE_`.

The FastAPI app has two more settings for the signed links of the files:
`STORAGE_LINK_SECRET`, the key that signs the links (a long random text,
the same in all processes; without it, each process signs with a random
key), and `STORAGE_LINK_SECONDS`, the time that a link works (default
3600). The links start with `PUBLIC_URL`, else with the URL of the
request.

## operations

An operation is an action of the app on an entity. The bindings
generate the code of the CRUD and list operations: a REST endpoint in
the FastAPI app, a server action in the Next.js app, and a data access
function in the React app.

| Key           | Content                                                                  |
| ------------- | ------------------------------------------------------------------------ |
| `kind`        | Required. `create`, `read`, `update`, `delete`, `list`, `custom`, or `query`. |
| `entity`      | Required. The entity of the operation. A query is in the slice of the entity. |
| `description` | Text. A custom operation and a query show it in their extension file.    |
| `params`      | `custom` and `query` only. A mapping from parameter name to a field (the field keys). |
| `returns`     | `custom` and `query` only. An entity name, or `none` (the default).      |
| `result`      | `query` only. A mapping from field name to a field: the fields of each row, for rows that are not records (see [Queries](#queries)). |
| `apis`        | `custom` only. The names of the [apis](#apis) that the logic calls.       |
| `lines`       | `create` and `update` only. The `one_to_many` relations whose records the operation writes with the record (see [Lines of a record](#lines-of-a-record)). |

The logic of a `custom` operation is a **generation gap**: the binding
generates the signature and the endpoint, and an extension file holds
the body, which the app developer writes
([traces.md](https://github.com/ds411/app-generator/blob/main/docs/traces.md#generation-gaps)).

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

### Queries

A `query` operation returns a list of rows for its params, for example
the free time slots of a room, a ranked feed, or the totals of each
month ([ADR 0045](https://github.com/ds411/app-generator/blob/main/docs/adr/0045-queries.md)). The logic is a generation gap:
a function of the extension file returns all rows in their order, and
the generated code returns one page of them.

```yaml
operations:
  open_tasks_of_person:
    kind: query
    entity: Task
    description: The open tasks of a person, the most urgent first.
    params:
      person_id: { type: uuid, required: true }
    returns: Task
  hours_by_status:
    kind: query
    entity: Task
    description: The count of the tasks and the estimate of each status.
    params:
      project_id: { type: uuid }
    result:
      status: { type: string, required: true, label: Status }
      tasks: { type: integer, required: true, label: Tasks }
      hours: { type: decimal, scale: 1, label: Hours }
```

- A query has `returns` (each row is a record of the entity) or
  `result` (each row has the fields of `result`), not both. The type of
  a field of `result` is a type that a view shows: `string`, `text`,
  `integer`, `decimal`, `boolean`, `date`, `datetime`, `uuid`, `email`,
  `url`, or `enum` (`unsuitable-field`). A field of `result` has no
  `unique`, `computed`, `translatable`, `filter`, `sequence`,
  `currency_field`, or `default`.
- The params have the types of the fields of `result`, and the names
  `limit` and `offset` are for the page (`reserved-name`).
- The FastAPI app has the endpoint `GET /<entity path>/<query name>`,
  for example `GET /tasks/open-tasks-of-person?person_id=...`, with the
  params as query parameters and the `limit` and `offset` of the lists.
  The response is a page: `items`, `total`, `limit`, and `offset`. A
  param that is not valid gives 422, and the stub of the extension file
  gives 501.
- The Next.js app has a server action, and the React app has a function
  with mock data, or a call of the endpoint of the FastAPI app with
  `x-react-data: api`. Both give a page of the rows, from 1.
- The permission of the query applies (see [access](#access)). The
  record rules of the roles for the entity of `returns` apply: a user
  gets only the records that the user may read. The extension file
  gives all rows, and the generated code removes the other records.
- An `operation` action cannot run a query (`unsuitable-operation`).
- A table, a card list, or a calendar shows the rows of a query, with
  filters for its params (see [Views of a query](#views-of-a-query)).

### Lines of a record

A `create` or an `update` operation with `lines` writes the record and
the records of its `one_to_many` relations in one transaction, for
example an invoice and its lines ([ADR 0035](https://github.com/ds411/app-generator/blob/main/docs/adr/0035-lines.md)). An
explicit operation replaces the operation of the same name of the CRUD
shorthand.

```yaml
entities:
  Invoice:
    crud: { views: [table, detail] }
    fields:
      number: { type: string, required: true }
    relations:
      lines: { kind: one_to_many, target: InvoiceLine, inverse: invoice }
  InvoiceLine:
    fields:
      amount: { type: decimal, required: true, scale: 2 }
    relations:
      invoice: { kind: many_to_one, target: Invoice, required: true, inverse: lines }
operations:
  create_invoice: { kind: create, entity: Invoice, lines: [lines] }
  update_invoice: { kind: update, entity: Invoice, lines: [lines] }
```

- The body of the FastAPI endpoint has a list for each relation of
  `lines`, for example `"lines": [{"amount": "12.00"}]`. An item has
  the fields and the relations of a new line, without the relation to
  the record, and an optional `id`.
- An update with the key replaces the lines: an item with the `id` of a
  line changes the given fields of that line, an item without an `id`
  is a new line, and the other lines go. Without the key, the lines
  stay.
- The rules, the workflows, and the events of the lines apply. An error
  in a line stores nothing, and the error response gives the place of
  the line in `errors`, for example `["body", "lines", 2]`.
- The lines use the permission and the record rules of the operation.
  The entity of the lines has no file fields.
- The front ends send the lines in the same request: the Next.js server
  action writes the record and the lines in one database transaction,
  the React app with mock data in one transaction of its mock stores,
  and the React app with the FastAPI app sends them to the endpoint. A
  form edits the lines with the widget `lines` (see [forms](#forms)).

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
| `embed`       | The origins of the websites that can show the page in a frame, for example `[https://www.example.com]` (see [Pages in frames](#pages-in-frames)). |
| `share`       | `true`: a user that may change the record of a detail page makes a secret link of it, for a guest without a sign-in (see [Secret links](#secret-links)). |
| `presence`    | `true`: a detail page shows the other signed-in users on the page of the same record, and a note when one of them types (see [Users on a record page](#users-on-a-record-page)). |
| `meta`        | The `description` and the `image` of the page for search engines and the previews of links (see [Page metadata](#page-metadata)). |

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

### Page metadata

`meta` gives a page a `description` and an `image` for search engines
and the previews of links, for example in a chat or a social network.
Each value is a text, or `$record.<field>` for a field of the record of
a page with an entity and a path parameter. The description takes a
`string` or a `text` field. The image takes an `image` or a `url`
field, or a text: an absolute URL, or a path of the app, for example
`/card.png` (a file of the `public` folder).

```yaml
pages:
  projects:
    meta:
      description: All the projects of the team, with their status and due dates.
      image: /projects.png
  project_detail:
    meta: { description: $record.description }
```

- A `$record.` value needs a public page: the definition has no `auth`,
  or the page is in `auth.public_pages`. The metadata shows to all
  users and crawlers.
- The Next.js app renders the metadata on the server: the `description`
  tag, the Open Graph tags (`og:title`, `og:description`, `og:image`),
  and the tags of the cards of X (`twitter:card`). An image path
  becomes an absolute URL with `PUBLIC_URL`, else with the host of the
  request.
- The Next.js app gives `/sitemap.xml` and `/robots.txt` for the public
  pages with `meta`. A page without path parameters has one URL. A page
  with path parameters has the URL of each record of its entity if each
  parameter is the ID, a required field, or the key of a required
  `many_to_one` relation (`<relation>_id`). `robots.txt` allows all
  pages but `/api/`, and gives the URL of the sitemap.
- The React app sets the description of the document while the page
  shows. A browser app has no server render: search engines that do not
  run JavaScript, and most previews of links, read only the title and
  the description of `index.html`. Use the Next.js app for pages that
  search engines must find.

### Pages in frames

Other websites can show a public page of the app in a frame, for
example a booking form on the website of a customer
([ADR 0032](https://github.com/ds411/app-generator/blob/main/docs/adr/0032-pages-in-frames.md)). `embed` lists the origins of
these websites. The page then shows without the app shell: no sidebar,
no top bar, and no header with the app title. The page search does not
find it.

```yaml
pages:
  holiday_widget:
    path: /embed/holidays
    title: Public holidays
    content: { view: public_holidays }
    embed: [https://www.example.com, https://intranet.example.com]
```

The other website shows the page with an `iframe`:

```html
<iframe src="https://tracker.example.org/embed/holidays" title="Public holidays"
        width="100%" height="600" style="border: 0"></iframe>
```

- Only a public page takes `embed`: the definition has no `auth`, or the
  page is in `auth.public_pages`. A page with `embed` has no `layout`.
- Each origin is `https://`, a host name in lower case, and an optional
  port, without a path, for example `https://www.example.com:8443`.
- The Next.js app sends the header `Content-Security-Policy:
  frame-ancestors 'self' <origins>` for the page (`next.config.ts`).
  The nginx configuration of the Docker image of the React app sends
  the same header. The servers of Vite (`pnpm dev`) do not send it.
- The other pages send `frame-ancestors 'self'`: other websites cannot
  show them in a frame.
- A browser can block the cookies of the app in a frame of another
  website. The page then shows in the language of the browser.

### Secret links

A user gives one record to a guest without an account with a secret
link, for example a booking to a guest of the meeting
([ADR 0049](https://github.com/ds411/app-generator/blob/main/docs/adr/0049-share-links.md)). The detail page of the record
takes `share: true`:

```yaml
# example: room-booking
pages:
  booking_detail:
    path: "/bookings/{id}"
    title: Booking
    entity: Booking
    content: { view: booking_detail }
    share: true
```

The page then has the button "Share" for a user that may call the
update operation of the entity. The button makes a link such as
`/shared/bookings/<token>`, and shows it one time. The user can make a
new link, which stops the old link, or revoke the link. The guest opens
the link without a sign-in and sees the detail view without the actions,
without the app shell, and without the tabs of the lists and of the
change log.

- The app has `auth`, and the page is not in `auth.public_pages`.
- The content of the page is a detail view. Its path ends with `{id}`
  and has no other parameter, and its entity has an update operation.
- An entity has one page with `share` at most. No other page has the
  path of the shared page: `/shared` and the path of the page, with
  `{token}` in the place of `{id}`.
- The link gives all fields of the record and of the related records
  that the view shows, also to a guest. A link does not expire.

### Users on a record page

A detail page shows the other signed-in users on the page of the same
record, so that two users do not change the record at the same time
([ADR 0052](https://github.com/ds411/app-generator/blob/main/docs/adr/0052-presence.md)). The page takes `presence: true`,
and the entity of its view is live ([Live updates](#live-updates)):

```yaml
# example: room-booking
entities:
  Booking:
    live: true
pages:
  booking_detail:
    presence: true
```

The header of the page then shows the avatar of each other user on the
record: the initials of the name, with the name as its tooltip. When a
user types in a form on the page, for example in the form of the button
"Edit", the other users see the note `<name> is typing.`. The name is
the display field of the user entity, else the user name.

- The app has `auth`, and the page is not in `auth.public_pages`.
- The content of the page is a detail view. Its path ends with `{id}`
  and has no other parameter, and its entity has `live`.
- The page calls the server when it opens, when the user starts or
  stops to type, and each 5 seconds. The typing stops 3 seconds after
  the last input. The server forgets a user 15 seconds after the last
  call, for example after a crash of the browser, and at once when the
  user leaves the page.
- The FastAPI app has `PUT /<entity>/{id}/presence` (with
  `{"typing": false}`, the answer has the other users) and
  `DELETE /<entity>/{id}/presence`. They need a read operation of the
  entity and its record rules. The Next.js app has server actions with
  the same checks. The changes of the users come to the other users on
  the record through the stream of the live updates, also through Redis
  with `LIVE_EVENTS_URL`.
- The React app with mock data shows no users.

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
      confirm: { from: [requested], to: confirmed, label: Confirm, run: notify_organizer }
      cancel: { from: [requested, confirmed], to: cancelled, label: Cancel }
```

- `field` is a stored enum field of `entity`. A field has one workflow.
- `initial` (optional) is the state of a new record. Without it, a new
  record can have any state.
- Each transition allows a change from each value in `from` to `to`.
  `to` is not in `from`.
- `message` (optional) is the error message of a change that no
  transition allows.
- `run` (optional) is a custom operation of `entity` that runs after the
  transition, in its transaction, like an [event](#events). After an
  update, the operations of the transitions run first, then the event
  `changed`.
- A change to the same state, and a change from or to no value, pass.

The FastAPI app gives a 422 error, the Next.js app a `ValidationError`,
and the React app (mock data) a `TransitionError`. The FastAPI app has a
test of each workflow.

## jobs

A job is work that the apps run at a time: on a schedule, or at the
time that a date field of each record gives
([ADR 0029](https://github.com/ds411/app-generator/blob/main/docs/adr/0029-jobs.md)). A job with an entity runs a custom
operation of the entity on each record of its filter, so the logic stays
in the extension file of the operation. A job without an entity is a
generation gap: hand-written code runs at each time of its schedule.

```yaml
# example: room-booking
jobs:
  booking_reminder:
    description: Remind the organizer one day before the booking starts.
    entity: Booking
    at: starts_at
    offset: -24h
    filter: { status: confirmed }
    operation: remind_organizer
  expire_requests:
    description: Cancel the requests that started without a confirmation.
    schedule: "0 * * * *"
    entity: Booking
    filter: { status: requested, starts_at: { lt: $now } }
    operation: expire_request
  weekly_report:
    description: Send the admins a report of the bookings of the week.
    schedule: "0 7 * * 1"
```

- A job has `schedule` or `at`, not both.
- `schedule` is a cron expression in UTC with five fields: the minute
  (0-59), the hour (0-23), the day of the month (1-31), the month (1-12
  or `jan`-`dec`), and the day of the week (0-7 or `sun`-`sat`, where 0
  and 7 are Sunday). A field is `*`, a value, a range (`1-5`), a step
  (`*/15`), or a list (`1,15`). The macros `@hourly`, `@daily`
  (`@midnight`), `@weekly`, `@monthly`, and `@yearly` (`@annually`)
  replace the five fields. When both day fields are not `*`, a day
  matches when one of them matches, as in cron and in Kubernetes. Put
  quotes around the expression: YAML reads a `*` at the start as an
  alias.
- `at` is a stored `date` or `datetime` field of `entity`. The job runs
  for each record at the time of the field, plus `offset`. The time of a
  `date` is midnight in UTC.
- `offset` (with `at`) is a whole number with a sign and a unit: `m`
  (minutes), `h` (hours), `d` (days), or `w` (weeks), for example `-24h`
  (24 hours before) or `4h`. The default is 0.
- `operation` is a custom operation of `entity`. Each run calls it on
  one record, with the default values of its params, so it cannot have
  a required param without a default.
- `filter` (optional) selects the records: the filter syntax of the
  [dashboards](#dashboards). `$now` is the time when the app runs the
  job, and `$today` its date in UTC.
- `user` names the user of each record: a `many_to_one` or `one_to_one`
  relation of `entity` to the user entity of `auth`, or `id` when
  `entity` is the user entity. A job whose operation calls an API with
  the authorization code flow needs it: the clients send the token of
  this user ([ADR 0033](https://github.com/ds411/app-generator/blob/main/docs/adr/0033-api-connections.md)). A run for a
  record whose user has no connection to the API does nothing.
- A job without `entity` has a `schedule`, and no `at`, `filter`,
  `operation`, or `user`.

A run is for one job, one record (or none), and one time. The apps keep
the runs in the table `job_runs`, with a key of the job, the record, and
the time, so each run runs one time, also with more than one worker. A
run looks back for the times that are not done, in a window of 60
minutes (`JOBS_WINDOW_MINUTES`): a job with a schedule runs the last
time of its schedule in the window, on each record that the filter
selects. A job with `at` runs each record whose time is in the window.
A change of the date field gives a new time, and so a new run. A failed
run rolls back its changes, goes into the log with the job and the
record, and runs again later while its time is in the window.

The FastAPI app runs the jobs in a worker process, `python -m
app.worker` ([bindings.md](https://github.com/ds411/app-generator/blob/main/docs/bindings.md#the-worker-of-the-fastapi-app)).
The generated tests of each job use a fixed clock. The Next.js app runs
each job in the route `POST /api/jobs/<job>`, which a scheduler calls
with the secret `JOBS_SECRET`: a Kubernetes CronJob, Cloud Scheduler,
or the service `jobs` of Compose
([bindings.md](https://github.com/ds411/app-generator/blob/main/docs/bindings.md#the-jobs-of-the-nextjs-app)). Both apps have
the same table `job_runs`. The React app (mock data) has no jobs.

## notifications

A notification gives users a notice when a record that concerns them
is created or changed ([ADR 0041](https://github.com/ds411/app-generator/blob/main/docs/adr/0041-notifications.md)). It names
the change of a record, the users that get the notice (the receivers),
and the text of the notice.

```yaml
# example: room-booking
notifications:
  booking_moved:
    entity: Booking
    event: changed
    fields: [starts_at, ends_at, room]
    receivers: [organizer]
    text: The booking {title} in {room} has a new time.
  booking_confirmed:
    entity: Booking
    transition: confirm
    receivers: [organizer]
    text: The booking {title} is confirmed.
    email: true
  booking_cancelled:
    entity: Booking
    transition: cancel
    receivers: [organizer]
    text: The booking {title} is cancelled.
    email: true
```

| Key           | Required | Content                                                         |
| ------------- | -------- | --------------------------------------------------------------- |
| `entity`      | Yes      | The entity of the records.                                      |
| `event`       | No       | `created` or `changed`: the change of a record that gives the notices. |
| `fields`      | No       | Only for `changed`: the stored fields and the `many_to_one` relations that the notification watches. The default is all. |
| `transition`  | No       | A transition of a workflow of the entity: `<transition>`, or `<workflow>.<transition>` when two workflows of the entity have a transition of the same name. |
| `receivers`   | Yes      | The users that get the notices: paths of relations to the user entity. |
| `text`        | Yes      | The text of a notice. A name in braces is a value of the record. |
| `email`       | No       | `true`: the receivers also get each notice by email (see [Emails of the notices](#emails-of-the-notices)). The default is `false`. |
| `description` | No       | Text. The page of the settings of the emails shows it.          |

- A notification has `event` or `transition`, not both. A notification
  `changed` gives the notices when an update gives one of `fields` a
  new value. A transition gives them when an update changes the field
  of the workflow from a state of `from` to the state `to`.
- Each receiver is a relation, or a path of relations with dots, from
  the entity to the user entity of `auth`, for example `assignee` or
  `project.team.members`. Each step is a `many_to_one` or a
  `many_to_many` relation, as in the owner of a record rule (see
  [access](#access)). A notification needs `auth`.
- Each user at the end of a receiver path gets one notice, except the
  user that made the change. A change without a signed-in user, for
  example in a job, gives a notice to all receivers.
- A name in braces in `text` is a stored field of the entity, except a
  file field, or a `many_to_one` relation: the display value of its
  record. A translatable field gives the value of the default language.
  The notice keeps the values from the time of the change.
- `text` is a key of the [translations](#translations): the apps give
  the text of a notice in the language of the user that reads it.
- The data access functions of the apps add the notices in the
  transaction of the change, after the [events](#events) and the
  [change log](#history). A change outside these functions gives no
  notice: SQL in a script, and the seed.
- The FastAPI app keeps the notices in the table `notices`.
  `GET /notices` gives the notices of the signed-in user, the newest
  first (`unread=true`: only the unread notices), `POST
  /notices/{id}/read` marks a notice read, and `POST /notices/read`
  marks all notices of the user read. The Next.js app keeps them in the
  same table. The React app with mock data keeps them in the browser
  tab until it closes, and with `x-react-data: api` it reads them from
  the FastAPI app.
- The top bar of a layout, and the header of the pages without a
  layout, show a bell: the count of the unread notices of the signed-in
  user, and the newest notices. A click on a notice
  marks it read, and opens the detail page of its record: the first
  page with a detail view of the entity and one parameter in its path.
  "Mark all read" marks all notices of the user read.

### Emails of the notices

A notification with `email: true` also sends each notice to the email
address of the receiver ([ADR 0044](https://github.com/ds411/app-generator/blob/main/docs/adr/0044-notice-emails.md)). It
needs `auth.delivery: smtp` (see [auth](#auth)): the apps send the
emails with the SMTP server of the settings `SMTP_*`.

- The notice waits for its email in the table `notices`. The built-in
  job `notice_emails` runs each minute (see [jobs](#jobs)), and sends
  the emails of the oldest 100 notices that wait. A job of the
  definition with the name `notice_emails` is an error.
- The subject is the title of the app and the text of the notice. The
  email has the text, the link to the detail page of the record, and
  the link to the page of the settings. The emails have the default
  language of the app. The links start with `FRONT_END_URL` (FastAPI)
  or `PUBLIC_URL` (Next.js).
- The page `/notice-settings` has a switch for each notification with
  `email: true`, with the name of the notification in words and the
  `description`. A user turns off the emails of a notification there.
  The notices stay in the bell. The bell has a link to the page. The
  FastAPI app has `GET /notices/settings` and
  `PUT /notices/settings/{notification}` (`{"email": false}`).
- The React app with mock data keeps the choices in the browser tab,
  and sends no emails. The mentions give no emails.

### Mentions

A `text` field with `mentions: true` can mention users
([ADR 0043](https://github.com/ds411/app-generator/blob/main/docs/adr/0043-mentions.md)). It needs `auth`: the users are the
records of the user entity. A computed or a translatable text cannot
have mentions.

```yaml
# example: room-booking
# in: entities.Booking.fields
notes: { type: text, max_length: 2000, mentions: true }
```

- A mention in the stored text is `@[<display value>](<ID of the
  user>)`: for example `@[Ann Lee]`, and then the ID of the user in
  parentheses. The display value has no brackets and no line breaks. A client of the
  API writes a mention in the same form.
- The widget of the field in a form is a text area. After `@` at the
  start of a word, a list suggests the users whose display value has
  the text after the `@`, and a choice puts the mention into the text.
  The list needs the permission of the list of the user entity, as a
  relation field to the user entity does.
- The views show a mention as `@` and the display value, with a link to
  the first page with a detail view of the user entity, if one exists.
- A create or a change of a record gives a notice to each user that the
  new text mentions and the text before did not: the built-in
  notification `@mention`, with the text "You are mentioned in
  {record}." (the display value of the record). The user that made the
  change, and an ID without a user, get no notice. The text of the
  notice is a key of the [translations](#translations).

## apis

The optional `apis` section names the third-party APIs that the app
calls, for example a payment service or the public holidays. An OpenAPI
document (3.0 or 3.1, YAML or JSON) describes each API. The bindings
generate a typed client for the operations in the list, and the
hand-written code of the app calls the client
([ADR 0019](https://github.com/ds411/app-generator/blob/main/docs/adr/0019-third-party-apis.md)).

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
| `security`     | The credential of each request: `scheme`, a security scheme of the document, and `env`, the environment variable of the API key or the token. For HTTP Basic: `username_env`, the environment variable of the user name, and `env`, the one of the password. For OAuth 2.0: `client_id_env` and `client_secret_env` in place of `env`, the optional `scopes`, and the optional `flow`: `clientCredentials` or `authorizationCode` (see below). The front-end builds make a variable with the prefix `NEXT_PUBLIC_` or `VITE_` public, so a secret cannot have it. Without `security`, the requests have no credential. |
| `expose`       | `true`: the FastAPI app has an endpoint for each operation, which calls the API with its secret, so that a front end can use the API. The default is `false`. |
| `title`        | The name of the API. The default is the title of the document.            |
| `description`  | Text.                                                                     |

- The document must be a local file. appgen reads no URL, and rejects a
  `$ref` to another file. The output manifest records the hash of each
  document, so the same files give the same app.
- Each operation ID must exist in the document, and must be a valid ID
  segment (letters, digits, and `_`).
- The clients support an API key in a header or a query parameter, a
  bearer token, HTTP Basic, and OAuth 2.0 with the client credentials
  flow or the authorization code flow.
- They send path, query, header, and cookie parameters. A cookie
  parameter is a text, a number, or a boolean, and goes in the header
  `Cookie`.
- A request body is JSON, a form (`application/x-www-form-urlencoded`),
  or a multipart form (`multipart/form-data`). The schema of a form is
  an object with properties. A form has only texts, numbers, booleans,
  and lists of these. A multipart form can also have files and objects:
  a file is a string with `format: binary` (or, in OpenAPI 3.1, with
  `contentMediaType` and without `contentEncoding`), and an object goes
  as JSON text. A file is a `Blob` in TypeScript and an `ApiFile` (the
  name, the content, and the media type) in Python. When the document
  gives more than one media type, the client sends JSON first, then a
  form, then a multipart form.
- An answer is JSON, text (a media type `text/*`: a string), or binary
  data (another media type: a `Blob` in TypeScript, `bytes` in Python).
  The client sends the media type of the answer in the header `Accept`.
  When the document gives more than one media type, JSON comes first,
  then text.
- With OAuth 2.0, the client gets an access token from the token URL of
  the client credentials flow of the scheme. It authenticates with
  HTTP Basic, with the client ID and the client secret, and asks for
  the scopes in `scopes`. Each scope must be a scope of the flow. A
  token URL that is a path (for example `/oauth/token`) is under the
  base URL of the API. The process keeps one token for the clients of
  an API, and two requests at the same time wait for the same token.
  The client gets a new token a little before the token ends, and one
  time after an answer with the status 401. The client ID is not a
  secret, but only the server apps get it.

```yaml
apis:
  finance:
    document: apis/finance.openapi.yaml
    base_url_env: FINANCE_API_URL
    security:
      scheme: oauth
      client_id_env: FINANCE_CLIENT_ID
      client_secret_env: FINANCE_CLIENT_SECRET
      scopes: [budgets:read]
    expose: true
    operations: [getBudget]
```

- With the authorization code flow (`flow: authorizationCode`, the
  default when the scheme has only this flow), the app calls the API in
  the name of a user ([ADR 0033](https://github.com/ds411/app-generator/blob/main/docs/adr/0033-api-connections.md)): a user
  connects an account of the service, and the client sends the access
  token of this user. The app needs `auth`, and no public operation can
  call the API. Each scope must be a scope of the flow. The authorization
  URL and the token URL can be paths under the base URL of the API. The
  FastAPI app has the routes of the flow under `/auth/connections/<api>`
  (in kebab case), and keeps the tokens of each user in the table
  `api_connections`, encrypted with a key from `AUTH_SECRET`. The client
  gets a new access token with the refresh token a little before the
  token ends, and one time after an answer with the status 401. A custom
  operation gets the client of the signed-in user, and gives 409 when
  the user has no connection. A job names the user of each record in
  `user`, and does nothing for a record whose user has no connection.
  The Next.js app has the same table, and the routes
  `/connections/<api>/start` and `/connections/<api>/callback`. Its
  server action gives an error result when the user has no connection.
  The front ends have the page `/connections` and a link to it in the
  layout: a signed-in user connects and disconnects the accounts there.
  The React app with `x-react-data: api` uses the routes of the FastAPI
  app: add the origin of the React app to `CORS_ORIGINS`. The React app
  with mock data keeps the connections in the browser. The OAuth app of
  the service must allow the URL of the callback. The Next.js app builds
  it from `PUBLIC_URL`, and the FastAPI app from `PUBLIC_URL` or the
  URL of the request.

```yaml
# not valid alone: the definition is tests/fixtures/api-connections.yaml.
apis:
  calendar:
    document: api-connections/calendar.openapi.yaml
    base_url_env: CALENDAR_API_URL
    security:
      scheme: oauth
      flow: authorizationCode
      client_id_env: CALENDAR_CLIENT_ID
      client_secret_env: CALENDAR_CLIENT_SECRET
      scopes: [events:read]
    operations: [listEvents]
```

- With HTTP Basic (a scheme with `type: http` and `scheme: basic`), the
  client sends the header `Authorization: Basic` with the Base64 of the
  UTF-8 bytes of `<user name>:<password>` (RFC 7617). `username_env`
  gives the user name, and `env` the password. Both are secrets: the
  deployment files read them from secrets, and a browser app has no
  client for the API (use `expose: true`). Without a password, the
  client sends no credential. For example, the Jira Cloud REST API takes
  the email address of an Atlassian account as the user name and an API
  token as the password, and its base URL is the URL of the site, for
  example `https://acme.atlassian.net`.

```yaml
# not valid alone: the definition is tests/fixtures/jira.yaml.
apis:
  jira:
    document: jira/jira.openapi.json
    base_url_env: JIRA_API_URL
    security: { scheme: basicAuth, username_env: JIRA_EMAIL, env: JIRA_API_TOKEN }
    operations: [getIssue, searchAndReconsileIssuesUsingJql, createIssue, addComment]
```

- The client has only the selected operations and the schemas that they
  use. Each answer has an example: the example of the document, or a
  sample from the schema. Some documents, for example the document of
  Jira Cloud, give the example of a JSON answer as a string with the
  JSON text. If the answer cannot be a string, the client reads the
  JSON text, or uses a sample when the text is not JSON.
- A custom operation names the APIs of its logic in `apis`. In the
  FastAPI app, its extension function then gets the clients of these
  APIs as arguments. The Next.js app has a server-only client for each
  API in `src/shared/api/<api>/`, which the extension file imports.
- The React app calls the APIs in the browser. A browser app cannot
  keep a secret, and cannot set a cookie for another site. Thus only an
  API without `security` and without a cookie parameter, or an API with
  `expose`, gets a client in `src/shared/api/<api>/`. With mock data,
  the client gives the example answers. For another API, `appgen
  generate` gives a warning: set `expose: true`, or call the API in a
  custom operation of the FastAPI app, and set `x-react-data: api`.
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
  parameter cannot hold (an object, or a list of lists), two parameters
  with the same name, a form body, or an answer that is not JSON
  (`unsuitable-operation`). Call such an operation in a custom
  operation.
- The environment variables of the apps (for example `DATABASE_URL`)
  are reserved. Two keys cannot use the same variable.
- A view can show the answer of an operation without hand-written code:
  see [Views of API data](#views-of-api-data).

## webhooks

The optional `webhooks` section names the endpoints that other systems
send events to, for example a payment service, a shipping service, or a
chat service. Each webhook has a path, a signature, and an optional
schema of the body. The FastAPI app checks the signature of each
request, and calls the hand-written logic of the webhook one time for
each event ([ADR 0028](https://github.com/ds411/app-generator/blob/main/docs/adr/0028-webhooks.md)). A webhook with
`format: email` receives the inbound emails that a mail service
forwards ([ADR 0030](https://github.com/ds411/app-generator/blob/main/docs/adr/0030-inbound-email.md)).

```yaml
webhooks:
  commits:
    description: The code host reports a commit that refers to a task.
    path: /webhooks/commits
    signature:
      scheme: hmac_sha256
      header: X-Signature-256
      prefix: "sha256="
      secret_env: COMMITS_WEBHOOK_SECRET
    body: { document: webhooks/commits.openapi.yaml, schema: CommitEvent }
  payments:
    path: /webhooks/payments
    signature:
      scheme: stripe
      secret_env: PAYMENTS_WEBHOOK_SECRET
      tolerance_seconds: 600
  shipping:
    path: /webhooks/shipping
    signature:
      scheme: hmac_sha256
      header: X-Shipping-Hmac
      encoding: base64
      secret_env: SHIPPING_WEBHOOK_SECRET
    event_id: { header: X-Shipping-Event }
  support:
    description: The mail service forwards an email to the support address.
    path: /webhooks/support
    format: email
    provider: postmark
    signature: { scheme: basic, secret_env: SUPPORT_INBOUND_CREDENTIALS }
```

| Key           | Content                                                                   |
| ------------- | ------------------------------------------------------------------------- |
| `path`        | Required. The path of the endpoint, for example `/webhooks/payments`. Each segment has lowercase letters, digits, `.`, `_`, `~`, and `-`. |
| `signature`   | Required. The check of the signature (see below).                         |
| `event_id`    | The location of the event ID: `field`, a property of the body (with `.` for a nested property, for example `message.id`), or `header`, a header. The default is `{ field: id }`. |
| `body`        | The schema of the body: `document`, the path of an OpenAPI document from the folder of the definition, and `schema`, the name of a schema in `components.schemas`. Without `body`, the event is a JSON value. |
| `format`      | `json` (the default): the body is a JSON event. `email`: the body is an inbound email of the mail service of `provider` (see [Inbound email](#inbound-email)). |
| `provider`    | Only `format: email`, and required: `mailgun`, `postmark`, or `sendgrid`. |
| `description` | Text.                                                                     |

The keys of `signature`:

| Key                 | Content                                                             |
| ------------------- | ------------------------------------------------------------------- |
| `scheme`            | Required. `hmac_sha256`, `stripe`, `mailgun`, or `basic`.           |
| `secret_env`        | Required. The environment variable of the secret that the sender and the app share. With `basic`, the secret is `<user name>:<password>`. |
| `header`            | Only `hmac_sha256`, and required: the header with the signature, for example `X-Hub-Signature-256`. |
| `prefix`            | Only `hmac_sha256`: a text before the signature, for example `sha256=`. The default is no prefix. |
| `encoding`          | Only `hmac_sha256`: `hex` (the default) or `base64`.                |
| `tolerance_seconds` | Only `stripe` and `mailgun`: the maximum difference in seconds between the time of the signature and now, from 1 to 86400. The default is 300. |

- `hmac_sha256`: the header has the HMAC-SHA256 of the raw body with the
  secret, in hex or in base64, after the prefix. For example, GitHub
  uses `X-Hub-Signature-256` with the prefix `sha256=`, and Shopify uses
  `X-Shopify-Hmac-Sha256` with base64.
- `stripe`: the header `Stripe-Signature` has `t=<time>,v1=<signature>`.
  The signature is the HMAC-SHA256 of `<time>.<body>` in hex. A time that
  is more than `tolerance_seconds` before or after now gives 401, so that
  a recorded request cannot come again later.
- `mailgun`: only with `provider: mailgun`. The fields `timestamp`,
  `token`, and `signature` of the form have the HMAC-SHA256 of
  `<timestamp><token>` with the signing key of Mailgun, in hex. An old
  time gives 401, as with `stripe`.
- `basic`: the header `Authorization` has the user name and the
  password of the secret (HTTP Basic authentication). A sender sends the
  header when its URL of the webhook has them, for example
  `https://<user name>:<password>@example.com/webhooks/support`. Use it
  only with HTTPS.
- The FastAPI app has the endpoint `POST <path>` for each webhook, in
  `app/webhooks/<webhook>/router.py`. The endpoint reads the raw body,
  and checks the signature with the secret. A wrong or missing signature
  gives 401. A body that is not JSON, or an event without an ID, gives
  400. A body that does not agree with the schema gives 422. A server
  without the secret gives 500.
- The answer is `{"event_id": "<id>", "repeated": false}`. The app keeps
  the event ID of each webhook in the table `webhook_events`. A repeated
  event gives `"repeated": true`, and the logic does not run again. The
  row and the changes of the logic are in one transaction: when the
  logic fails, the app does not keep the row, and the sender can deliver
  the event again.
- The logic of each webhook is a gap: the function `handle_<webhook>` in
  the extension file `app/webhooks/<webhook>/handler_ext.py`. It gets
  the database session, the event, and the headers of the request. The
  event is a Pydantic model of the schema, or a `JsonValue` without
  `body`. Until the function has the logic, the endpoint gives 501. A
  `ProblemError` of the logic gives its status to the sender.
- The Next.js app has the route handler `app/<path>/route.ts` for each
  webhook, and the feature slice `src/features/<webhook>-webhook/`. The
  endpoint gives the same statuses and the same answer, and keeps the
  event IDs in the table `webhook_events` too. It adds the row before
  the logic runs, and removes the row when the logic fails. The changes
  of the logic are not in the transaction of the row: when the logic
  fails after a change, the change stays.
- The logic of each webhook of the Next.js app is a gap: the function
  `handle<Webhook>` in the extension file
  `src/features/<webhook>-webhook/api/<webhook>-webhook.ext.ts`. It gets
  the event and the headers of the request. The event has the TypeScript
  type of the schema, and a zod schema of the type checks the body.
  Without `body`, the event is `unknown`. Until the function has the
  logic, the endpoint gives 501. A `WebhookError` of the logic gives its
  status to the sender.
- The React app has no server, and leaves out the webhooks.
- The path of a webhook cannot be the path of another webhook, of a
  page, or of the endpoints of an entity (`duplicate-path`). It cannot
  be under a route of the apps, for example `/auth`, `/apis`, or `/docs`
  (`reserved-name`).
- The environment variables of the apps are reserved. The secret
  variable cannot be the variable of an API or of another webhook, and
  cannot have the prefix `NEXT_PUBLIC_` or `VITE_`.
- The document must be a local file, as for `apis`. The schema must be
  in the document, and the property of the event ID must be in the
  schema. The output manifest records the hash of each document.

### Inbound email

A webhook with `format: email` receives the emails that a mail service
forwards to the app, for example the emails to a support address. The
app reads the request of the mail service into one email, and calls the
logic of the webhook one time for each `Message-ID` header.

| Provider   | Request of the mail service                                   | Schemes            |
| ---------- | ------------------------------------------------------------- | ------------------ |
| `mailgun`  | A route with the action `forward`: a form with the fields `from`, `subject`, `body-plain`, `body-html`, `message-headers`, and the attachments as files. | `mailgun`, `basic` |
| `postmark` | The inbound webhook: JSON with `FromFull`, `ToFull`, `CcFull`, `Subject`, `TextBody`, `HtmlBody`, `Headers`, and `Attachments`. | `basic`            |
| `sendgrid` | The Inbound Parse webhook, not the raw MIME message: a form with the fields `from`, `to`, `cc`, `subject`, `text`, `html`, `headers`, and the attachments as files. | `basic`            |

- The logic gets the email: the `Message-ID` (`message_id`, or
  `messageId` in the Next.js app), the sender of the `From` header, the
  receivers of `To` and `Cc` (each an address and an optional name), the
  subject, the text, the HTML, the `In-Reply-To` header, and the
  attachments. The FastAPI app gives the Pydantic model `InboundEmail`
  of `app/core/inbound_email.py`, and the Next.js app the type
  `InboundEmail` of `@/shared/webhooks`.
- An attachment gives only its name, its media type, and its size. The
  app does not keep the content of the files.
- The event ID is the `Message-ID` header. An email without one gets the
  SHA-256 hash of the body as its event ID. The answer and the repeated
  emails are as for the other webhooks.
- A wrong signature gives 401. A body without a sender gives 400. A
  server without the secret gives 500.
- A webhook with `format: email` needs `provider`, and its scheme must
  be a scheme of the provider (`invalid-option`). It has no `body` and
  no `event_id` (`invalid-option`). A webhook without `format: email`
  has no `provider` and no scheme `mailgun` (`invalid-option`).

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
can also show the answer of an API operation in place of the records
(see [Views of API data](#views-of-api-data)), or the rows of a query
(see [Views of a query](#views-of-a-query)).

**Table** (`kind: table`):

| Key            | Content                                                         |
| -------------- | --------------------------------------------------------------- |
| `columns`      | Required. A mapping from column name to column.                 |
| `sort`         | `field` and `direction` (`asc` or `desc`).                      |
| `filters`      | A mapping from filter name to filter.                           |
| `pagination`   | `mode`, `page_size`, and `page_sizes`.                          |
| `row_actions`  | Actions of each row.                                            |
| `row_click`    | The row action that a click on a row runs.                      |
| `selection`    | Boolean: check boxes on the rows.                               |
| `bulk_actions` | Actions of the selected rows.                                   |
| `order_field`  | An `integer` field of a manual order: the user moves the rows (see [Manual order](#manual-order)). |

A column has `field` (default: the column name), `label`, `format`,
`badge`, `width` (a `size` token), `align` (`start`, `center`, `end`),
`sortable`, `link` (a page), and `hide_below` (a breakpoint). The
formats are `text`, `number`, `currency`, `percent`, `date`,
`datetime`, `relative_time`, `boolean`, `badge`, `email`, `url`, and
`avatar`. The default format is the `format` of the field, else a
format for the field type. `avatar` is for a relation (the initials of
the record) and for an `image` field (the image in a circle).

A filter has `kind`: `search` (`fields`), `select` (`field`,
`multiple`), `boolean` (`field`), `date_range` (`field`), `near`
(`field`, `distance`), `area` (`field`), or `available` (`rule`). All
filters take `label`, and all filters except `near`, `area`, and
`available` take `default`. The `default`
of a `select` filter of a relation to the user entity can be `$me`, the
signed-in user (see [The signed-in user](#the-signed-in-user)): the view
starts with the records of the user, and a clear of the filter shows all
records.

The filters `near` and `area` are for a `point` field
([ADR 0046](https://github.com/ds411/app-generator/blob/main/docs/adr/0046-geo-points.md)). `near` keeps the records whose
point is at most a distance from a point. `distance` is the distance in
kilometers until the user picks another one, by default 10. `area` keeps
the records whose point is in a box, for example the visible part of a
map. The list endpoint of the FastAPI app takes these query parameters
for a filter of the field path `<path>`:

- `near`: `<path>_near`, a point `<lat>,<lng>`, for example
  `38.72,-9.14`, and `<path>_distance` in kilometers. The default of
  the distance is the `distance` of the first `near` filter of the path.
  The app gives the distances on a sphere (the haversine formula).
- `area`: `<path>_area`, a box `<south>,<west>,<north>,<east>`, for
  example `38.69,-9.23,38.80,-9.09`. A box whose west is greater than
  its east crosses the antimeridian.

The filter `available` keeps the records without a related record whose
range overlaps the days that the user picks
([ADR 0047](https://github.com/ds411/app-generator/blob/main/docs/adr/0047-available-filter.md)), for example the rooms
without a booking. `rule` is a relation to many records (`one_to_many`
or `many_to_many`) and a `no_overlap` rule of the related entity, with
a dot: the `start` and the `end` of the rule give the range of a related
record (see [Entity rules](#entity-rules)). The filter shows the widget
of a date range.

```yaml
# example: room-booking
ui:
  views:
    free_rooms:
      kind: table
      entity: Room
      columns: { name: {}, capacity: {} }
      filters:
        free: { kind: available, rule: bookings.no_double_booking, label: Free on }
```

- The range of a related record is from its start up to its end: a
  range that ends when another starts does not overlap it, as for the
  rule. A related record without a start or an end has no range.
- On date fields, the picked days are the range of a new related
  record: from the first day up to the end day, for example a check-in
  and a check-out. A record is free on the day that a booking ends.
  Without an end day after the first day, the range is the first day.
- On date-time fields, the picked days are whole days in UTC: from the
  start of the first day to the end of the last day.
- Without a first day, the filter keeps all records.
- The list endpoint of the FastAPI app takes `<relation>_free_from` and
  `<relation>_free_to`, for example
  `?bookings_free_from=2026-03-06&bookings_free_to=2026-03-09`. The
  Next.js app and the React app with mock data read the ranges of the
  related records with the access of the list of the records, and filter
  in the browser. The ranges come from all related records: a record
  rule that hides the bookings of another user does not make a room
  free.
- `appgen validate` reports a relation that does not exist or is not to
  many records (`unknown-reference`, `unsuitable-field`), and a rule
  that does not exist or is not a `no_overlap` rule (`unknown-reference`,
  `invalid-option`).

`pagination.mode` is `pages` (the default: page buttons) or `scroll`.
A list with `scroll` shows `page_size` records, and shows the next page
when the end of the list comes into view, or after a click on
`Show more`. It keeps the shown records, and a new filter or sort shows
the first page again. With `x-react-data: api`, each next page is one
request of one page to the list endpoint, and a change of the records
loads the shown pages again. `scroll` is for the tables and the card
lists of entities, and does not take `page_sizes`.

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

```yaml
# in: ui.views
activity_feed:
  kind: table
  entity: Comment
  columns: { author: { format: avatar }, body: {}, posted_at: { format: relative_time } }
  sort: { field: posted_at, direction: desc }
  pagination: { mode: scroll, page_size: 25 }
```

**Card list** (`kind: cards`): `card` (`title`, `subtitle`, `badge`,
`fields`, `footer`, `image`), `grid`, and the `sort`, `filters`,
`pagination`, and `row_actions` of a table. The card `image` is an
`image` field: the cover image at the top of the card.

**Board** (`kind: board`): `group_by` (an `enum` field), `columns` (a
mapping from enum value to `label`, `color`, and `limit`), `card`, and
`move` (an update or custom operation that runs when a card moves to
another column), and `responsive`. `responsive` has `below` (a
breakpoint token) and `layout`: on screens narrower than the
breakpoint, `stack` shows the columns one under the other, and `scroll`
shows each column almost as wide as the screen, with snap scroll.
Without `responsive`, the columns scroll sideways. `order_field` gives
the cards of each column a manual order (see [Manual order](#manual-order)).

#### Manual order

A table or a board with `order_field` has a manual order
([ADR 0039](https://github.com/ds411/app-generator/blob/main/docs/adr/0039-manual-order.md)): the view sorts the records by
this `integer` field, and a record without a value comes last. The user
moves a row of a table by drag and drop, or with the arrow keys on the
handle of the row, and a card of a board by drag and drop, also to
another column. The app writes the new value with the update operation
of the entity.

```yaml
entities:
  Task:
    fields:
      rank: { type: integer, min: 0 }
ui:
  views:
    backlog:
      kind: table
      entity: Task
      columns: { title: {}, status: {}, assignee: {} }
      order_field: rank
```

- The moved record gets the middle value between the values of its
  neighbors, rounded down: one update. At the top, the lower neighbor is
  0. At the end, the value is the value of the last record plus 1024.
- When no integer is free, or a neighbor has no value, the app gives the
  records of the list 1024, 2048, 3072, and so on, in the new order, and
  updates the records whose value changes.
- The list is the list that the user sees: the filtered records of a
  table, or the cards of a column. A table that the user sorts by a
  column does not show the handles. With `x-react-data: api`, a move
  loads all records of the view, so that new values cover the other
  pages too.
- A view with `order_field` takes no `sort`. The field has no `unique`,
  no `max`, no `computed`, no `sequence`, and a `min` of 1 or less. The
  entity needs an update operation. With `access`, a role that may not
  call the update operation cannot move the records.
- The mock data of the React app is in memory: a reload shows the order
  of the mock data again.

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

**Map** (`kind: map`): the records on a map, with a marker for each
record, and the list of the records in the visible area of the map
([ADR 0046](https://github.com/ds411/app-generator/blob/main/docs/adr/0046-geo-points.md)). `point` (a `point` field, also
through a relation) gives the place of a record, `label` is its text
(default: the display field), and `link` is a page that a record opens.
A click on a marker, Enter on a focused marker, and a click on a record
of the list open the page. A map takes `filters` and `sort` (the order
of the list, default: the label), as a table does, but no `area`
filter: a move of the map gives the area.

```yaml
entities:
  Site:
    display_field: name
    crud: { operations: [list, read], views: [detail] }
    fields:
      name: { type: string, required: true }
      location: { type: point, required: true, label: Location }
pages:
  site_map: { path: /map, title: Map, content: { view: site_map } }
  site: { path: "/sites/{id}", title: Site, entity: Site, content: { view: site_detail } }
ui:
  views:
    site_map:
      kind: map
      entity: Site
      point: location
      label: name
      link: site
      filters:
        nearby: { kind: near, field: location, label: Near, distance: 5 }
```

- The map first shows all its markers. After each move, the list shows
  the records in the visible area. With `x-react-data: api`, the map
  loads the records of the list endpoint with `<point>_area`, and the
  first load (before the first move) has all records.
- The map loads its tiles from a tile server. The build variable
  `NEXT_PUBLIC_MAP_TILES` (Next.js) or `VITE_MAP_TILES` (React) gives
  the URL of the tiles, with `{z}`, `{x}`, and `{y}`, and
  `NEXT_PUBLIC_MAP_ATTRIBUTION` or `VITE_MAP_ATTRIBUTION` their
  attribution. Without a value, the map uses the standard tiles of
  OpenStreetMap: read their tile usage policy before a production use.
- An `area` filter of a table or a card list shows the same map in a
  popover: the user moves the map, and uses its visible area.

**Detail** (`kind: detail`): one record, from the path parameter of the
page. `header` (`title`, `subtitle`, `badges`), `sections` (`title`,
`description`, `fields`, `columns`, or `custom: true`), `tabs`
(`label`, `icon`, and `sections`, or `relation` and `view`, or
`history: true`, or `custom: true`), and `actions`. A tab with
`history: true` shows the change log of the record (see
[History](#history)): each entry with the user, the time, and the
changes, the newest first. An entry of a change has a restore button,
if the user may update the record. The entity of the view must keep a
change log (`invalid-option`).

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
        history: { label: History, icon: history, history: true }
        activity: { label: Activity, custom: true }
```

#### Views of API data

A table, a card list, or a detail view can show the answer of an
operation of an API (see [apis](#apis) and
[ADR 0022](https://github.com/ds411/app-generator/blob/main/docs/adr/0022-api-views.md)). The view has `source:
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

#### Views of a query

A table, a card list, or a calendar can show the rows of a query (see
[Queries](#queries) and [ADR 0045](https://github.com/ds411/app-generator/blob/main/docs/adr/0045-queries.md)). The view has
`query: <operation>` in place of `entity`. Each param of the query gets
its value from a filter of the view or from `params`, not from both
(`invalid-option`), and each required param needs a value
(`missing-key`).

- `filters` is a mapping from a name to a filter: `param` (default: the
  name), `label` (default: the label of the param), and `default`. The
  filter of a text, a number, a date, or a date and time is an input of
  that type, the filter of an enum is a select, and the filter of a
  boolean is a switch: on gives `true`, and off gives `false` to a
  required param, else no value. While the filter of a required param
  has no value, the view shows a message and does not run the query.
- `params` gives the other params: a literal of the type of the param,
  or `$route.<name>` for a path parameter of the page (`invalid-value`).
- The fields of the view are the fields of the rows: the fields of the
  entity of `returns` and `id` (not its relations or its file fields),
  or the fields of `result` (`unknown-reference`, `unsuitable-field`).
- A table has `columns` (`field`, `label`, `format`, `width`, `align`,
  `link`, `hide_below`), a card list has `card` (`title`, `subtitle`,
  `fields`, `footer`) and `grid`, and both have `pagination` (the mode
  `pages`). A calendar has `start`, `end`, `label`, `mode`, and `link`:
  `start` and `end` are date or date-time fields of the same type, and
  rows that are not records need `label`.
- `link` opens the page of a record: only for rows that are records.
- The query gives the order of the rows, so the view has no `sort` and
  no `order_field`, and its rows are not records of the view: it has no
  actions, no row actions, no bulk actions, and no selection.
- The page of the view has no `entity`, and its path has each `$route`
  parameter of the view. A tab or a list widget of a dashboard cannot
  show a view of a query (`unsuitable-view`).

The view loads one page of the rows with the function of the query. In
the Next.js app, the function calls the server action of the query, so
the extension file runs on the server, with the permission and the
record rules. The React app calls the endpoint of the FastAPI app with
`x-react-data: api`, else the extension file with the mock data. A
calendar loads all rows, 200 at a time.

```yaml
operations:
  open_tasks_of_person:
    kind: query
    entity: Task
    params:
      person_id: { type: uuid, required: true }
    returns: Task
  tasks_by_status:
    kind: query
    entity: Task
    params:
      due_before: { type: date }
    result:
      status: { type: string, required: true, label: Status }
      tasks: { type: integer, required: true, label: Tasks }
pages:
  open_tasks:
    path: "/people/{id}/open-tasks"
    title: Open tasks
    content: { view: open_task_table }
  task_counts: { path: /task-counts, title: Tasks by status, content: { view: status_cards } }
ui:
  views:
    open_task_table:
      kind: table
      query: open_tasks_of_person
      params: { person_id: $route.id }
      columns:
        title: { link: task_detail }
        due_date: { align: end }
      pagination: { page_size: 10 }
    status_cards:
      kind: cards
      query: tasks_by_status
      filters:
        due_before: { label: Due before }
      card: { title: status, fields: [tasks] }
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
| `defaults`      | A literal, `$route.<param>` for a path parameter of the page, or `$me` for the signed-in user. |
| `on_success`    | `toast`, `close`, and `navigate`.                                  |

A form field has `widget`, `label`, `placeholder`, `help`, `span`,
`rows`, `step`, `options`, and `rules` (`required`, `min_length`,
`max_length`, `pattern`, `min`, `max`, each with `value` and
`message`). The widgets are `text`, `textarea`, `number`, `select`,
`radio`, `checkbox`, `switch`, `date`, `datetime`, `relation`, `file`
(for a `file` or an `image` field), `point` (for a `point` field),
`lines` (for a `one_to_many` relation), and `custom` (a generation
gap). The default widget comes
from the field type.

The widget `lines` is a lines editor ([ADR 0035](https://github.com/ds411/app-generator/blob/main/docs/adr/0035-lines.md)):
a table with a row for each record of the relation, and a column for
each name in `fields`, a field or a single relation of the lines. The
operation of the form must write the relation (`lines` of the
operation), and each required field of the lines needs a column. The
editor adds, changes, and removes rows, and checks each row with the
rules of the lines. Below the rows, the form shows the computed fields
of the record with totals of the lines, before the save. An update form
reads the lines of the record first. With the FastAPI app, the entity
of the lines needs a `list` operation.

```yaml
operations:
  create_project: { kind: create, entity: Project, lines: [budget_lines] }
ui:
  forms:
    plan_project:
      entity: Project
      operation: create_project
      fields:
        name: {}
        key: {}
        owner: {}
        budget_lines: { widget: lines, fields: [item, amount] }
```

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

A dashboard has `title`, `description`, `grid`, `period`, and
`widgets`. Each widget has `kind`, `label`, and `span`:

| Kind     | Keys                                                                      |
| -------- | ------------------------------------------------------------------------- |
| `stat`   | `entity`, `aggregate` (`count`, `sum`, `avg`, `min`, `max`), `field`, `filter`, `format`, `icon`, `color`, `link`, `period_field`, `compare`, `snapshots`. |
| `chart`  | `chart` (`bar`, `line`, `donut`), `entity`, `group_by`, `interval`, `aggregate`, `field`, `filter`, `badge`, `period_field`; or `snapshots` and `days`. |
| `list`   | `view`, `filter`, `sort`, `limit`, `link`, `period_field`.               |
| `custom` | A generation gap.                                                         |

The default `format` of a stat widget is the `format` of its field (for
`sum`, `avg`, `min`, and `max`), else `number`.

An aggregate of a field with `currency_field` adds amounts in the
currency of each record. A stat widget needs a filter on one currency,
for example `filter: { customer.currency: eur }`, and shows the sum in
that currency. A chart widget needs the same filter, or a `group_by` of
the currency field. `appgen validate` reports the other cases.

A chart of a `date` or a `datetime` field groups the records by
`interval`: `day`, `week`, `month` (the default), or `year`. A week
starts on the first day of the week of the locale of the selected
language (see [translations](#translations)), else on Monday. A date and
time is in the interval of its day in UTC. The chart shows each interval
from the first date to the last date, also the intervals without
records, and then the records without a date (`None`). Only a chart of
dates takes `interval`.

```yaml
# in: ui.dashboards.overview.widgets
tasks_by_week:
  kind: chart
  chart: line
  entity: Task
  group_by: due_date
  interval: week
```

A stat widget with `snapshots: daily` has a value for each day
([ADR 0042](https://github.com/ds411/app-generator/blob/main/docs/adr/0042-stat-snapshots.md)): the built-in job
`stat_snapshots` of the FastAPI and the Next.js apps runs at 00:00 UTC,
and stores the value of the stat at that time as the value of the day.
`$today` in the filter is the day of the run. A line chart with
`snapshots`, the name of a stat widget of the same dashboard with
`snapshots: daily`, shows the stored values of the last `days` days (2
to 366, 30 by default), for example the burndown of the open tasks. A
day without a value is not a point of the line. A chart of snapshots
takes no `entity`, `group_by`, `interval`, `aggregate`, `field`,
`filter`, `badge`, or `period_field`, and its stat takes no
`period_field` or `compare`. A snapshot has the value of all records,
so the entity of the stat cannot have a record rule, and the filter of
the stat cannot have `$me`: the job has no signed-in user. The chart is
empty until the first run of the job. The React app with mock data has
no stored values: its chart shows the value of today. The Next.js app
computes a snapshot in the database, so the field of the aggregate is a
stored field of the entity of the stat. A job with the name
`stat_snapshots`, or an entity with the table `stat_snapshots`, is a
generation error.

```yaml
# in: ui.dashboards.overview.widgets
open_tasks:
  kind: stat
  entity: Task
  filter: { status: { ne: done } }
  snapshots: daily
burndown:
  kind: chart
  chart: line
  snapshots: open_tasks
  days: 14
```

A filter maps a field path to a value, or to operators (`eq`, `ne`,
`lt`, `lte`, `gt`, `gte`, `in`, `not_in`). `$today` and `$now` are
date values. `$me` is the signed-in user, for a relation to the user
entity (see [The signed-in user](#the-signed-in-user)).

A dashboard with `period` has a picker of a date range above its
widgets ([ADR 0038](https://github.com/ds411/app-generator/blob/main/docs/adr/0038-dashboard-period.md)). `default` is the
range of a new page (default `last_30_days`), and `ranges` are the
ranges that the picker offers, in their order. The ranges are `today`,
`last_7_days`, `last_30_days`, `last_90_days`, `last_365_days`,
`this_week`, `this_month`, `this_year` (each to today), `last_week`,
`last_month`, `last_year` (each the whole unit before), `all` (no
limits), and `custom` (the user picks the first and the last day). The
default `ranges` are `last_7_days`, `last_30_days`, `last_90_days`,
`this_month`, `last_month`, `this_year`, and `all`. A week starts on
the first day of the week of the locale of the selected language, else
on Monday.

A widget with `period_field` (a `date` or a `datetime` field of its
entity, or of the entity of the view of a list widget) shows only the
records whose value of that field is in the days of the range. A date
and time is in the range of its day in UTC. The other widgets show all
records. A stat widget with `compare: previous` also shows the change
from the period of the same length before the range, as a percentage,
for example `+12%` for the last 30 days against the 30 days before. A
range without a first or a last day (`all`) has no change. The period
needs a widget with `period_field`, and `period_field` needs the period
of the dashboard. `appgen validate` reports the other cases.

```yaml
# in: ui.dashboards
sales:
  title: Sales
  period: { default: last_30_days, ranges: [last_7_days, last_30_days, this_month, all, custom] }
  widgets:
    new_tasks:
      kind: stat
      entity: Task
      period_field: due_date
      compare: previous
```

The FastAPI binding computes each stat, chart, and list widget in the
database, with one endpoint for each widget. The endpoint of a widget
with `period_field` takes `start` and `end`, the first and the last day
of the range. The React app with `x-react-data: api` sends them, and
reads the value of the previous period of a `compare` from the same
endpoint. A widget for that binding
cannot read a computed field, because the database has no column for
it.

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
user name and a password ([ADR 0011](https://github.com/ds411/app-generator/blob/main/docs/adr/0011-auth.md)), or with an
OpenID Connect provider ([ADR 0020](https://github.com/ds411/app-generator/blob/main/docs/adr/0020-providers.md)).

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
  delivery: smtp
  second_factor:
    totp: true
    required_roles: [admin]
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
  ([ADR 0016](https://github.com/ds411/app-generator/blob/main/docs/adr/0016-sign-up.md)). It is off by default. `fields`
  names the fields of the user entity that the sign-up form asks for.
  It must have each required field without a default, and it cannot
  have the role field or a computed field. With `access`,
  `default_role` is the role of a new user. Without it, a new user gets
  the default of the role field.
- `sign_up.verify_email` makes a new user confirm the email address
  before the first sign-in ([ADR 0023](https://github.com/ds411/app-generator/blob/main/docs/adr/0023-email-verification.md)).
  It is off by default. The app sends a message with a link to the
  address, and the user can sign in only after the user opens the link.
  `true` gives a link that stays valid for one day. The mapping form
  sets the time: `verify_email: { token_minutes: 60 }` (5 to 10080,
  default 1440). The address is the user name field if its type is
  `email`, else the first required `email` field of the user entity: the
  user entity must have one. The users that an administrator gives a
  password, and the users of a provider, need no verification.
- `password_reset` lets a user who forgot the password set a new one
  with a link in a message ([ADR 0017](https://github.com/ds411/app-generator/blob/main/docs/adr/0017-password-reset.md)). It
  is off by default. `token_minutes` (5 to 1440, default 60) is the
  time that a link stays valid. A link is valid only one time.
- `delivery` selects how the apps send the messages of `verify_email`
  and `password_reset`. With `extension` (the default), the delivery
  (for example an email) is a generation gap: an extension file of the
  app sends the messages. With `smtp`, the apps send them as emails
  with an SMTP server, and the delivery is not a gap. The settings
  `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `SMTP_FROM` (the sender), and `SMTP_TLS` (`starttls`
  by default, `tls`, or `none`) select the server. Without `SMTP_HOST`,
  the apps write the links to the log with `ENVIRONMENT=development`,
  and give an error in production. `smtp` needs an address: the user
  name field of the type `email`, or a required `email` field of the
  user entity.
- `second_factor` lets each user with a password turn on a second factor
  of the sign-in: the codes of an authenticator app
  ([ADR 0024](https://github.com/ds411/app-generator/blob/main/docs/adr/0024-second-factor.md)). It is off by default.
  `totp: true` selects the time-based one-time passwords of RFC 6238,
  the only method now. With `access`, `required_roles` names the roles
  that must use it: their first sign-in turns it on. The role of the
  sign-up can be one of them only with `verify_email`, because without
  it the sign-up starts a session at once. A sign-in with a provider
  does not ask for the second factor.
- `providers` are OpenID Connect providers that the users can sign in
  with, for example the sign-in of the company
  ([ADR 0020](https://github.com/ds411/app-generator/blob/main/docs/adr/0020-providers.md)). The name of a provider is a
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
- `authorize_params` adds fixed parameters to the authorization request
  of a provider, for example `{ identity_provider: EntraID }` for a user
  pool of Amazon Cognito: the user pool then sends the users at once to
  that identity provider, not to its own sign-in page. A parameter that
  the flow sets (`response_type`, `client_id`, `redirect_uri`, `scope`,
  `state`, `nonce`, `code_challenge`, and `code_challenge_method`) is
  not valid (`reserved-name`).
- `trust_email: true` makes the apps accept the email address of an ID
  token also when the token does not mark it as verified
  (`email_verified` is missing, `false`, or `"false"`). Use it only for a
  provider that gives only the addresses of the company, for example a
  user pool of Amazon Cognito with a single-tenant Entra ID as its SAML
  identity provider: the user pool does not mark the address of a SAML
  user as verified. See [Sign-in with Amazon Cognito and Entra
  ID](https://github.com/ds411/app-generator/blob/main/docs/cognito-entra-id.md).
- `password: false` turns off the sign-in with a password: the users
  sign in only with `providers`. It needs a provider, and it cannot
  have `sign_up`, `password_reset`, or `second_factor`.
- No page can use the path `/sign-in`, `/sign-up` with a sign-up,
  `/verify-email` with `verify_email`, `/forgot-password` and
  `/reset-password` with a password reset, `/second-factor` with a
  second factor, a path under `/auth/` with providers, or
  `/connections` and a path under `/connections/` with an API with the
  authorization code flow, or `/notice-settings` with a notification
  with `email: true`: they are the pages of the front ends.

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
`ENVIRONMENT=development`, and gives 501 in production. With
`delivery: smtp`, the app has no extension file: `app/core/mail.py`
sends each message with `smtplib` in a thread, so that the request does
not block the other requests. The subject and the text of a message are
in the language of the request. With
`second_factor`, `POST /auth/second-factor/setup` gives a new secret
and its `otpauth://` URI, and `POST /auth/second-factor/confirm` with a
valid code turns the factor on and gives 10 recovery codes one time.
Then `POST /auth/sign-in` gives a challenge for 5 minutes, not a token,
and `POST /auth/sign-in/second-factor` with the challenge and a code,
or a recovery code, gives the token. Each code and each recovery code
is valid one time. After 5 wrong codes in a row, the codes of the user
give 429 for 15 minutes. A user of a required role gets the challenge
of the setup, and turns the factor on with it. `GET
/auth/second-factor` gives the state of the factor, `POST
/auth/second-factor/disable` with a code turns it off, and `python -m
app.cli disable-second-factor <user name>` turns it off for a user who
lost the codes. With
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
hashes, and no command `set-password`. With a password, the seed of
the FastAPI app gives each new seed user the password in
`SEED_PASSWORD`. The Next.js app has the page `/sign-in` and a session
cookie, and its seed also gives each user the password in
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
password reset, with the stub of the FastAPI app. With `delivery:
smtp`, `src/shared/auth/mail.ts` sends them with the package
`nodemailer` instead. The React app calls
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

With `second_factor`, each front end has the page `/second-factor` for
the signed-in user, and a link to it in the top bar. The page turns the
factor on: it shows the new secret as a QR code and as text (the key),
asks for a code of the authenticator app, and then shows the recovery
codes one time. The browser makes the QR code with the package `uqr`,
so the secret goes to no service on the network. The page also shows
the number of the recovery codes that are left, and turns the factor
off with a code or a recovery code, but not for a required role. After
the password of a user with the factor, the sign-in page asks for a code
of the authenticator app or a recovery code. A user of a required role
without the factor turns it on before the sign-in. The Next.js app uses
server actions with the rules of the FastAPI app, and keeps the factor
in the table `credentials`. An administrator turns off the factor of a
user who lost the codes in the database: set the column
`totp_enabled_at` of the user to null. The React app with
`x-react-data: api` calls the endpoints of the FastAPI app. The React
app with mock data has the factor as a demonstration: the secrets and
the recovery codes stay in the browser tab.

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

### The signed-in user

The value `$me` is the signed-in user, as the value of a relation to
the user entity. It needs the section `auth`. A queue of tickets, for
example, starts with the tickets of the agent, and the agent can still
clear the filter and see all tickets. These places take `$me`:

- The `default` of a `select` filter of a view, for a `many_to_one`,
  `one_to_one`, or `many_to_many` relation to the user entity. With
  `multiple`, write `[$me]`.
- The `filter` of a widget of a dashboard, for the same relations.
- The `defaults` of a form, for a field of the form with such a
  relation: a new record belongs to the user.
- The `filter` of a computed field with totals, for a `many_to_one`
  relation of the related records to the user entity: each user gets
  the total of the own records.

A job runs without a user, so its filter does not take `$me`. Without a
signed-in user, `$me` is a value that no record has: `eq` keeps no
records, and `ne` keeps all records.

```yaml
# example: room-booking
# in: ui
views:
  my_bookings:
    kind: table
    entity: Booking
    columns: { title: {}, room: {}, starts_at: {} }
    filters:
      organizer: { kind: select, field: organizer, default: $me }
forms:
  new_booking:
    defaults: { organizer: $me }
dashboards:
  overview:
    widgets:
      my_bookings:
        kind: stat
        label: My bookings
        entity: Booking
        filter: { organizer: $me }
```

The FastAPI app reads the user of the token of each request, also on a
public endpoint, and gives it to the SQL of the totals and of the
widgets. The Next.js app reads the user of the session: the root layout
gives it to the views, the forms, and the widgets, and the repositories
read it for the totals. The React app reads the user of the browser
tab. With mock data, the mock store reads it for the totals.

## access

The optional `access` section gives each user a role, and each role the
operations and pages that it may use ([ADR 0012](https://github.com/ds411/app-generator/blob/main/docs/adr/0012-access.md)).
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
- `records` gives the role record rules ([ADR 0018](https://github.com/ds411/app-generator/blob/main/docs/adr/0018-owner-rules.md),
  [ADR 0025](https://github.com/ds411/app-generator/blob/main/docs/adr/0025-record-rules.md)): for each entity, the role uses
  only some of the records. A rule has `owner`, `where`, or both.
  `operations` is `read` (the lists and the reads), `change` (the
  creates, the changes, the deletes, and the custom operations), or both
  (the default). A rule for `read` also applies to the changes. A rule
  does not apply to the public operations.
- `owner` gives the records of the user. It is a relation of the entity
  to the user entity, or a path of relations with dots, such as
  `project.team.members`. Each step is a `many_to_one` or a
  `many_to_many` relation, and the last step goes to the user entity.
  All rules of an entity with an `owner` use the same `owner`.
- `where` gives the records with some values: a value or a list of
  values for each field. The field is a stored `string`, `text`,
  `email`, `url`, `integer`, `boolean`, or `enum` field, and each value
  suits the field.

```yaml
# not valid alone: the entities Task, Project, and Team are not in the base example
records:
  Project: { owner: team.members, operations: [read] }
  Task:
    owner: project.team.members
    where: { status: [open, in_progress] }
```

Here the role reads the projects of its teams, and uses the open tasks of
these projects. A rule with `owner` and `where` gives the records that
suit both.

The FastAPI app gives 403 for an operation that the role may not call.
With a record rule, a list gives only the records of the rule, and a
read, a change, a delete, or a custom operation on another record gives
404. A create or a change that gives a record out of the rule gives
403, and the record does not change. With an `owner` of one relation, a
create sets the owner to the user. With a path, the request gives the
first relation, and the path must lead to the user.
An embedded record of another entity follows the rules of that entity
too: a hidden embedded record of one is `null` and its ID stays, and an
embedded list leaves out the hidden records.
The Next.js app shows "not found" for a page, and gives an error for a
server action. The React app (mock data) does the same checks in the
browser, so they are a demonstration, not a protection.
The menus, the page search, the links, and the actions of the front
ends show only the pages and the operations that the role allows. A
group of a menu without an allowed page does not show.
The front ends apply the record rules too. The server actions of the
Next.js app use only the records of the rule, a detail page of another
record shows "not found", and a create or a change out of the rule
gives an error. The React app shows the records that the FastAPI app
gives, and with mock data the mock store applies the rules in the
browser, as a demonstration. For a user of a rule, the create and update
forms do not show the owner field of one relation and the fields of a
condition with one value: a new record belongs to the user, and gets
the value of the condition.

### Memberships

`memberships` gives a user a role in one record of a scope entity, for
example a team or a course ([ADR 0048](https://github.com/ds411/app-generator/blob/main/docs/adr/0048-memberships.md)). A
record of the membership entity has the user, the scope record, and the
role. A user can be a teacher in one course and a student in another.

```yaml
# not valid alone: the entities Course, Lesson, and Enrollment are not in the base example
memberships:
  entity: Enrollment
  user: person
  scope: course
  role_field: role
  roles:
    teacher:
      label: Teacher
      operations: [update_course, create_lesson, update_lesson]
    student:
      label: Student
      operations: [read_course, list_lessons, read_lesson]
  paths:
    Lesson: course
```

- `entity` is the membership entity. `user` is its `many_to_one`
  relation to the user entity, and `scope` its `many_to_one` relation
  to the scope entity. The scope entity is not the user entity.
- `role_field` is an `enum` field of the membership entity. Each key of
  `roles` is a value of that field.
- `operations` names the operations that the role gives on the records
  of its scopes, or `*` for all operations of the entities of the scope.
  An operation is an operation of the scope entity or of an entity in
  `paths`, and not a query.
- `paths` gives the other entities of the scope: for each entity, the
  path of `many_to_one` relations with dots to the scope entity, for
  example `lesson.course`. The scope entity has no path: its records are
  the scopes. The membership entity can have a path too, for example
  `course`: then a role can list the memberships of its scopes.

The role of `roles` comes first: if it gives the operation, the
memberships do not apply. Else a membership of the user with a role
that gives the operation lets the user call it, on the records of the
scopes of these memberships only. The FastAPI app gives 403 for an
operation that no role of the user gives. A list gives the records of
these scopes. A read, a change, or a delete of a record in another
scope of the user gives 403, and of a record out of all scopes of the
user gives 404. A create or a change that puts a record out of these
scopes gives 403, and the record does not change.

The front ends apply the memberships too. The server actions of the
Next.js app use only the records of the scopes, with the same errors. The
React app shows the records that the FastAPI app gives, and with mock
data the mock store applies the memberships in the browser, as a
demonstration. An action of an operation that only a membership gives
shows on a record in a scope whose role gives the operation, and not on
the other records: the UI asks the server for the operations of the
memberships of the user on the records of the page. An action of a
create or a list shows if a membership in some scope gives it.

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

### Values in each language

A `string` or `text` field with `translatable: true` has a value in each
language of `translations`, for example the title of a task. The other
fields have one value for all languages.

```yaml
entities:
  Task:
    fields:
      title: { type: string, required: true, max_length: 200, translatable: true }
      description: { type: text, translatable: true }
```

- The record keeps the value of the default language in the field, and
  the values of the other languages in `<field>_translations`. A value
  of another language is optional: without it, the app shows the value
  of the default language.
- The search, the sort, the filters, and `unique` use the value of the
  default language.
- The rules of the field, for example `max_length`, apply to the value
  of each language. A `required` field needs a value in the default
  language.
- `appgen validate` reports `translatable` without the section
  `translations`, on a field of another type, on a computed field, and
  on a param of an operation (`invalid-option`). Another field or relation cannot have
  the name `<field>_translations` (`duplicate-name`).

The FastAPI app reads and writes the values in the language of the
request:

- A read gives the value of the language of the request in the field,
  else the value of the default language. `<field>_translations` is
  null. With the query parameter `translations=all`, it has the values
  of all languages by their codes, the default language included.
- A create or a change sets the value of the language of the request. A
  new record without a value of the default language takes the value as
  its default value too. `<field>_translations` sets the value of each
  language that it gives. Null or an empty text removes the value of a
  language that is not the default language.
- An app that exists gets the new column with the next migration
  (`alembic revision --autogenerate`). The records keep their values as
  the values of the default language.

The React and Next.js apps show the value of the selected language in
the views, the detail views, and the relation fields, else the value of
the default language. A form has an input for each language of a
translatable field, for example `Title (English)` and `Title (Deutsch)`.
The Next.js app stores the values as the FastAPI app does, and
`pnpm db:generate` makes the migration of the new column. The mock data
of the React app and the seed data of the Next.js app have a value in
each language: the value of the default language with the label of the
language, for example `Write the release notes (Deutsch)`. With
`x-react-data: api`, the React app asks the API for the values of all
languages.

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
- The second factor: `Second factor`,
  `Sign in with your password and a code of an authenticator app on your phone.`,
  `Turn on`,
  `Scan the QR code with an authenticator app, or enter the key. Then enter the code that the app shows.`,
  `QR code of the key`, `Key`, `Code`, `The second factor is on.`,
  `Keep these recovery codes in a safe place. Each code signs you in one time if you lose the authenticator app.`,
  `Recovery codes`, `Continue`, `Recovery codes left: {count}`,
  `Code or recovery code`, `Turn off`,
  `Your role must use a second factor.`,
  `Your role must use a second factor. Turn it on to sign in.`,
  `Code of the authenticator app`,
  `Without the app, enter a recovery code.`,
  `The sign-in has ended. Sign in again.`, `The code is not correct.`,
  `Too many wrong codes. Try again later.`,
  `The second factor needs a password. Set a password first.`,
  `The second factor is off.`.
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
  `Try again`, `Yes`, `No`, and the manual order: `Order`,
  `Move the row`, `The row did not move.`.
- Filters: `No matching records`, `Change or reset the filters.`,
  `Reset the filters`, `Reset`, `{label}: all`, `{count} chosen`,
  `No value has this name.`, `Clear the filter`, `Clear {label}`,
  `Enter the required values`, `The view needs a value in: {names}.`.
- Boards and calendars: `Move to`, `Drop a card here`,
  `The column has more than {limit} cards.`, `The card did not move.`,
  `Show more` (a board of the API client),
  `Previous week`, `Next week`, `Previous month`, `Next month`, `Today`,
  `Calendar mode`, `Week`, `Month`.
- Maps and the geo filters (see [views](#views)): `In the map`,
  `{count} in the map`,
  `No records in this part of the map. Move the map, or zoom out.`,
  `{label}: lat, lng`, `Distance from {label}`, `{distance} km`,
  `Use this area`, and the inputs of a point: `Latitude`, `Longitude`.
- Date pickers: `Navigation bar`, `Go to the next month`,
  `Go to the previous month`, `Choose the month`, `Choose the year`,
  `Today, {date}`, `{date}, selected`.
- Dashboards: `View all`, `No data yet`, `Other`, `None`, and the
  period: `Period`, `Today`, `Last 7 days`, `Last 30 days`,
  `Last 90 days`, `Last 365 days`, `This week`, `This month`,
  `This year`, `Last week`, `Last month`, `Last year`, `All time`,
  `Custom range`, `Pick the days`, `{change} from the previous period`.
- The bell of the notices (see [notifications](#notifications)):
  `Notices`, `Notices: {count} unread`, `Mark all read`,
  `No notices yet.`, `Email settings`.
- The page of the emails of the notices (see
  [Emails of the notices](#emails-of-the-notices)): `Notice emails`,
  `Choose the notices that also come to you by email. The bell shows all notices.`,
  `The change did not succeed.`, and the text of the email
  `Turn off these emails on the page of the settings:`.
- The mentions (see [Mentions](#mentions)): `Users` (the list of the
  suggestions), and the text of the notice
  `You are mentioned in {record}.`.
- The change log of a record (see [History](#history)): `History`,
  `Created`, `Changed`, `Deleted`, `Restored`, `Restore`, `Newer`,
  `Older`, `No changes yet.`, `The history did not load.`,
  `The old values are back.`, `The restore did not succeed.`,
  `Only the entry of a change has old values to restore.`.
- Actions and forms: `Cancel`, `Close`, `Saved.`,
  `The action did not succeed.`, `The form did not save.`,
  `Select a value`, `Search`, `No results.`, `Loading…` (a search on
  the server), `Select a record`,
  `Select records`, `Clear`, `Remove {label}`, `Pick a date`, `Time`,
  `Command Palette`, `Search for a command to run...`, and the label of
  the input of a language of a translatable field, `{field} ({language})`.
- The file widget of the forms: `Drop a file here, or`, `Select a file`,
  `Select another file`, `Remove the file`,
  `Types: {types}. Largest file: {size}.`, `Largest file: {size}.`.
- The lines editor of the forms (ADR 0035): `Add a line`, `No lines yet.`,
  `{field}, line {number}`, `Remove line {number}`,
  `Line {number}: {message}`, `The lines did not load.`.
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
  `Your role may not give a record these values.`,
  `Your role in the scope of the record may not do this operation.`,
  `The sign-in failed.`, `The user name or the password is not correct.`,
  `The browser does not keep the session.`,
  `A user with this user name exists.`.
- The messages of an upload of a file (the mock data of the React app,
  and the server actions of the Next.js app): `Select a file.`,
  `The file is larger than {size}.`,
  `The type {type} is not allowed. Use one of: {types}.`.
- The rate limit of the Next.js app:
  `Send not more than {limit} requests in each minute.`, and with the
  store in Redis
  `The store of the rate limit is not available. Try again later.`.
- The webhooks of the Next.js app:
  `The server has no secret for the webhook {name}.`,
  `The signature of the webhook is not valid.`,
  `The body of the webhook is not valid JSON.`,
  `The webhook has no event ID.`,
  `The body of the webhook does not agree with its schema.`,
  `The logic of the webhook failed. Deliver the event again later.`,
  `The body of the webhook is not a valid email.`.
- The page of the connections to the APIs with the authorization code
  flow: `Connections`,
  `Connect your accounts of other services, so that the app can use them in your name.`,
  `The account is connected.`, `Connected`, `Not connected`, `Connect`,
  `Disconnect`. The flow of the Next.js app:
  `Connect an account of the API {api} first.`,
  `The server has no client ID or client secret for the API {api}.`,
  `The authorization server gave the error '{error}'.`,
  `The callback has no code. Connect the account again.`,
  `The authorization server did not accept the code. Connect the account again.`,
  `The token endpoint of the API {api} did not answer correctly.`,
  `The state of the callback is not correct. Connect the account again.`,
  `The connection failed.`.
- The secret links of the records (ADR 0049): the button `Share`, its
  dialog `Share the record`,
  `A person with the link sees the record without a sign-in.`, `Link`,
  `Copy the link`, `Copy the link now: it shows one time only.`,
  `The record has a link, made at`, `The record has no link.`,
  `Make a link`, `Make a new link`, `Revoke the link`,
  `The link is copied.`, `Copy the link from the field.`,
  `The link is revoked.`, `The link did not load.`,
  `The link was not made.`, `The revoke did not succeed.`, and the
  shared page: `The link is not valid.`,
  `The record is not shared, or its link was revoked.`,
  `Something went wrong`.
- The other users on a record page (ADR 0052): the list
  `Other users on this page`, and the notes `{name} is typing.`,
  `{first} and {second} are typing.`, and `{count} users are typing.`.

### Messages of the FastAPI app

The FastAPI app gives these messages in the default language. Add a key
to translate one. The rules and the workflows give their own messages.

- The titles of the problem details: `Bad Request`, `Unauthorized`,
  `Forbidden`, `Not Found`, `Method Not Allowed`, `Conflict`,
  `Content Too Large`, `Unsupported Media Type`, `Unprocessable Content`,
  `Too Many Requests`, `Internal Server Error`, `Not Implemented`,
  `Bad Gateway`, `Service Unavailable`.
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
  `Your role may not do this operation.`,
  `Your role may not give a record these values.`,
  `Your role in the scope of the record may not do this operation.`,
  `The server has no AUTH_SECRET.`,
  `If the user name exists, the user gets a message with a reset link.`,
  `The reset link is not valid, was used, or has ended.`.
- The verification of the email address:
  `Open the link in the message to confirm the email address.`,
  `Confirm the email address first: open the link in the message.`,
  `If the user name needs a confirmation, the user gets a message with a link.`,
  `The link is not valid, or has ended.`.
- The secret links of the records: `The link is not valid.`.
- The second factor: `The code is not correct.`,
  `Too many wrong codes. Try again later.`,
  `The sign-in has ended. Sign in again.`,
  `The second factor needs a password. Set a password first.`,
  `The second factor is on.`, `The second factor is off.`,
  `Your role must use a second factor.`.
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
- The connections of the users to the APIs with the authorization code
  flow: `Connect an account of the API {api} first.`,
  `The server has no client ID or client secret for the API {api}.`,
  `The authorization server gave the error '{error}'.`,
  `The callback has no code. Connect the account again.`,
  `The authorization server did not accept the code. Connect the account again.`,
  `The token endpoint of the API {api} did not answer correctly.`,
  `The state of the callback is not correct. Connect the account again.`,
  `The connection failed.`.
- The webhooks: `The server has no secret for the webhook {name}.`,
  `The signature of the webhook is not valid.`,
  `The body of the webhook is not valid JSON.`,
  `The webhook has no event ID.`,
  `The body of the webhook is not a valid email.`.
- The files of the file fields: `The file is larger than {size}.`,
  `The type {type} is not allowed. Use one of: {types}.`, and for a link
  that is not valid `The link is not valid, or has ended.`.
- The change log: `The record has no history entry with the ID {id}.`,
  `Only the entry of a change has old values to restore.`.
- The notices: `You have no notice with the ID {id}.`,
  `The notification {notification} has no emails.`, and the text of the
  email `Turn off these emails on the page of the settings:`.

## Extension keys

A key that starts with `x-` is an extension key, as in OpenAPI. The
root and each element can have them. The DSL keeps them and does not
check them. A binding can read them, for example the React binding
reads `x-mock-count` on an entity (the number of mock records). A
binding declares a schema for the keys that it reads, so `appgen
validate` and `appgen generate` report a wrong key or value of a binding
in use ([bindings.md](https://github.com/ds411/app-generator/blob/main/docs/bindings.md#extension-keys)). Any other unknown key
is an error.

## Reserved sections

No top-level key is reserved now. The sections that
[ADR 0002](https://github.com/ds411/app-generator/blob/main/docs/adr/0002-app-definition-dsl-v0.md#how-the-out-of-scope-features-fit-in-later)
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
diagnostics as JSON. [`examples/invalid/`](https://github.com/ds411/app-generator/tree/main/examples/invalid/) has one broken definition for
each diagnostic code. `appgen generate` validates the definition first,
and writes no file if it is not valid.
