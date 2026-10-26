# Write a new app definition

Read this file when the task is to write an app definition from a
description of an app. [dsl.md](dsl.md) is the full reference of the DSL,
with an example for each section. [diagnostics.md](diagnostics.md) gives
the cause and the fix of each diagnostic code.

## Steps

1. Read the description of the app. List the things that the app keeps
   records of: each one is an **entity**. List the fields of each
   entity, and the relations between the entities.
2. Copy the [start definition](#the-start-definition) into `app.yaml`.
   Keep its first line, the schema line. Change `app`.
3. Write `entities`: the fields first, then the relations. Validate:
   `appgen validate app.yaml --format json`.
4. Write the operations. Use the CRUD shorthand (`crud`) for the
   create, read, update, delete, and list operations. Add a `custom`
   operation only for logic that is not CRUD. Validate.
5. Write `pages`, and the parts of `ui` that the pages use: the views,
   the forms, the dashboards, the layouts, and the menus. The CRUD
   shorthand can also give a default table view, detail view, and forms.
   Validate.
6. Add the optional sections only if the description asks for them:
   `workflows`, `auth`, `access`, and `translations`. Validate.
7. Generate the app with the binding of the task, and check it, as the
   CLI loop of `SKILL.md` tells.

Validate after each step, and fix all diagnostics of a step before the
next step. One error can cause more errors later in the file.

## Sections

| Section        | Required | Content                                                    | Add it when                                    |
| -------------- | -------- | ---------------------------------------------------------- | ---------------------------------------------- |
| `version`      | Yes      | The DSL version: `0`.                                      | Always.                                        |
| `app`          | Yes      | `name` (`^[a-z][a-z0-9-]*$`), `title`, and `description`.  | Always.                                        |
| `entities`     | Yes      | The data model: fields, relations, rules, and `crud`.      | Always.                                        |
| `operations`   | No       | Operations that `crud` does not give, for example `custom`. | The app has logic that is not CRUD.           |
| `pages`        | No       | The routes of the front end, with their content.           | The app has a front end (`nextjs` or `react`). |
| `ui`           | No       | Tokens, badges, layouts, menus, views, forms, dashboards, and defaults. | The pages show views, forms, or dashboards. |
| `workflows`    | No       | State machines on `enum` fields.                           | A status field allows only some changes.       |
| `apis`         | No       | Third-party APIs: a local OpenAPI document and the operations that the app calls. | The app calls an outside service. |
| `webhooks`     | No       | The endpoints that other systems send signed events to: the path, the signature, and the schema of the body. | An outside service sends events to the app, for example payments. |
| `auth`         | No       | The sign-in: the user entity and the public parts.         | The users must sign in.                        |
| `access`       | No       | Roles, and the operations and pages of each role. Needs `auth`. | The users have roles with different rights. |
| `translations` | No       | The UI text in more than one language.                     | The app has more than one language.            |
| `seed`         | No       | The records that the apps start with, by entity and record key. | The task gives data, for example a list of rooms. |
| `storage`      | No       | The place of the files: a local folder (`local`) or an S3-compatible service (`s3`). | An entity has a `file` or an `image` field. |

A key that starts with `x-` is an extension key of a binding, for
example `x-mock-count` (the number of mock records of the React app).
Add one only if the task asks for it.

## Names and IDs

The names make the element IDs, and the traces in the generated code
and in the hand-written code refer to the IDs. A later rename changes
the IDs and breaks the traces of hand-written code. So:

- Choose stable names from the domain of the app, in English, for
  example `Booking`, `starts_at`, and `cancel_booking`.
- Entity names are in PascalCase (`^[A-Z][A-Za-z0-9]*$`). The names of
  fields, relations, params, operations, pages, enum values, and UI
  elements are in snake case (`^[a-z][a-z0-9_]*$`).
- Do not name a field `id`: each entity has an implicit `id` of type
  `uuid`.
- Use singular entity names (`Booking`, not `Bookings`). Give
  `plural_label` for an irregular plural, for example `People` for
  `Person`.

## The start definition

A small, complete definition: two entities with the CRUD shorthand, a
custom operation, a start page with a dashboard, and a list page and a
detail page for each entity. It validates, and it generates with each
binding.

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ds411/app-generator/main/schema/app.schema.json
version: 0

app:
  name: room-booking
  title: Room Booking
  description: Book the meeting rooms of a team.

entities:
  Room:
    crud:
      views: [table, detail]
      forms: [create, update]
    display_field: name
    fields:
      name: { type: string, required: true, unique: true, max_length: 80 }
      capacity: { type: integer, required: true, min: 1, max: 500 }
    relations:
      bookings: { kind: one_to_many, target: Booking, inverse: room }

  Booking:
    crud:
      views: [table, detail]
      forms: [create, update]
    display_field: title
    fields:
      title: { type: string, required: true, max_length: 120 }
      starts_at: { type: datetime, required: true }
      ends_at: { type: datetime, required: true }
      status: { type: enum, values: [requested, confirmed, cancelled], default: requested }
    relations:
      room: { kind: many_to_one, target: Room, required: true, on_delete: restrict, inverse: bookings }
    rules:
      ends_after_start:
        kind: compare
        field: ends_at
        op: gt
        other: starts_at
        message: The end must be after the start.

operations:
  cancel_booking:
    kind: custom
    entity: Booking
    description: Cancel a booking, and tell the person who booked the room.
    returns: Booking

pages:
  dashboard:
    path: /
    title: Dashboard
    content: { dashboard: overview }
  bookings:
    path: /bookings
    title: Bookings
    entity: Booking
    content: { view: booking_table }
    actions:
      new_booking: { kind: form, form: new_booking, label: New booking, icon: plus }
  booking_detail:
    path: "/bookings/{id}"
    title: Booking
    entity: Booking
    content: { view: booking_detail }
    actions:
      edit: { kind: form, form: edit_booking, label: Edit, icon: pencil }
      cancel:
        kind: operation
        operation: cancel_booking
        label: Cancel
        variant: destructive
        confirm: { title: "Cancel the booking?", confirm_label: Cancel booking }
  rooms:
    path: /rooms
    title: Rooms
    entity: Room
    content: { view: room_table }
    actions:
      new_room: { kind: form, form: new_room, label: New room, icon: plus }
  room_detail:
    path: "/rooms/{id}"
    title: Room
    entity: Room
    content: { view: room_detail }
    actions:
      edit: { kind: form, form: edit_room, label: Edit, icon: pencil }

ui:
  layouts:
    app_shell:
      sidebar: { navigation: main, title: Room Booking, icon: door-open }
      topbar: { breadcrumbs: true }
  navigation:
    main:
      items:
        dashboard: { page: dashboard, icon: layout-dashboard }
        bookings: { page: bookings, icon: calendar-days }
        rooms: { page: rooms, icon: door-open }
  dashboards:
    overview:
      title: Overview
      widgets:
        rooms: { kind: stat, label: Rooms, entity: Room, aggregate: count, icon: door-open, link: rooms }
        requested:
          kind: stat
          label: Requested bookings
          entity: Booking
          aggregate: count
          filter: { status: requested }
          link: bookings
  defaults:
    layout: app_shell
```

The custom operation `cancel_booking` is a generation gap: the
generated app has a stub for it, and the check reports it in `gaps`.

## Entities and relations

- Give each entity a `display_field`: the field that names a record in
  lists, links, and the fields of other records.
- The field types are `string`, `text`, `integer`, `decimal`,
  `boolean`, `date`, `datetime`, `uuid`, `email`, `url`, `enum` (with
  `values`), and `json`. Use `decimal` with `scale` for money, and
  `format: currency` to show it as money.
- A `one_to_many` relation needs `inverse`: the `many_to_one` relation
  on the target that points back. Write both sides, as `Room.bookings`
  and `Booking.room` above.
- Give `required` and `on_delete` (`restrict`, `cascade`, or
  `set_null`) to each `many_to_one` relation.
- A `many_to_many` relation needs no foreign key field. If the target
  has the other side too, give `inverse` on both sides.
- `rules` check more than one field (`compare`), or more than one
  record (`unique`, `no_overlap`).
- A `computed` field gets its value from other fields, for example
  `computed: hours(starts_at, ends_at) * room.hourly_rate`.

## Operations

`crud` gives the operations with fixed names. `<entity>` is the entity
name in snake case, and `<plural>` comes from `plural_label` (`People`
gives `people`), or else from a simple rule on the entity name: add
`s`, or `es` after `s`, `x`, `z`, `ch`, and `sh`, or change a `y` after
a consonant to `ies`. The rule knows no irregular plurals: `Person`
gives `list_persons`, and `Category` gives `list_categories`.

| `crud` value                         | Gives                                                         |
| ------------------------------------ | ------------------------------------------------------------- |
| `crud: true`                         | `create_<entity>`, `read_<entity>`, `update_<entity>`, `delete_<entity>`, and `list_<plural>`. |
| `crud: [create, list]`               | Only these operations.                                        |
| `crud: { views: [table, detail], forms: [create, update] }` | All five operations, the views `<entity>_table` and `<entity>_detail`, and the forms `new_<entity>` and `edit_<entity>`. |

The pages, the actions, and `access` can name these operations, views,
and forms. A `custom` operation has `entity`, `description`, `params`
(fields, as the fields of an entity), and `returns` (an entity or
`none`). Its logic is a generation gap. Use one only if the logic is
not CRUD.

## Pages and the UI

- Give the app a start page with the path `/`.
- A page that shows one record has a path parameter, for example
  `"/bookings/{id}"`, and a detail view or an update form as content.
- `content` is one of `view: <view>`, `form: <form>`,
  `dashboard: <dashboard>`, or `custom: true`.
- A page action of the kind `form` opens a form, `operation` runs an
  operation on the record of the page, and `navigate` opens a page.
- Give a layout with a menu (`ui.layouts`, `ui.navigation`), and set it
  as `ui.defaults.layout`.
- The keys `custom: true`, `widget: custom`, a form rule or an action
  with `kind: custom`, and a dashboard widget with `kind: custom` are
  generation gaps. Use them only for a part that the DSL cannot
  describe.
- Style values (colors, sizes, gaps) are references to tokens of
  `ui.tokens`, for example `"{color.primary}"`.

## YAML traps

- Put quotes around a text with `: `, `?`, `#`, `{`, `}`, `[`, `]`, or
  `,` in a flow mapping (`{ ... }`), for example
  `{ title: "Cancel the booking?" }`.
- Put quotes around a path with a parameter (`"/rooms/{id}"`) and a
  token reference (`"{color.primary}"`).
- YAML reads `yes`, `no`, `on`, and `off` as booleans. Put quotes around
  such a value when it is a name, for example an enum value `"on"`.
- Each collection of named elements is a mapping from the name to the
  element, never a list.
