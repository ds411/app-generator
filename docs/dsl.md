# App definition reference

An app definition is one YAML file that describes an application: its
data model, its operations, its pages, and its UI. appgen validates the
file and generates the code of an app from it, for one binding (a target
stack). This page is the reference for each section of the file, with
examples. [ADR 0002](adr/0002-app-definition-dsl-v0.md) and
[ADR 0003](adr/0003-ui-dsl.md) give the reasons for the design.
`examples/project-tracker/app.yaml` is a complete example.

## Contents

- [The file](#the-file)
- [Names and IDs](#names-and-ids)
- [app](#app)
- [entities](#entities)
- [operations](#operations)
- [pages](#pages)
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
| Field, relation, param, operation, page, enum value, UI element | `^[a-z][a-z0-9_]*$` | `due_date` |
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
| Operation    | `operations.complete_task`                 |
| Param        | `operations.assign_task.params.note`       |
| Page         | `pages.task_board`                         |
| Page action  | `pages.task_detail.actions.delete`         |
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
and optional `title`, `description`, `actions`, and `states`.

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
        title: { placeholder: What needs to be done? }
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

These top-level keys are reserved for later versions: `auth`,
`access`, `workflows`, and `translations`. The validator reports "not
supported in this version" for each of them. A later version adds them
as optional sections, so that the definitions that exist stay valid.
[ADR 0002](adr/0002-app-definition-dsl-v0.md#how-the-out-of-scope-features-fit-in-later)
gives the plan for each one.

## Validation

`appgen validate <file>` checks the YAML syntax, the keys and values
against the schema, the names, and the references between elements
(for example a relation to an entity that does not exist, a token loop,
or a view field of the wrong type). Each diagnostic has a code, a
message, and the line and the column. `--format json` writes the
diagnostics as JSON. `examples/invalid/` has one broken definition for
each diagnostic code. `appgen generate` validates the definition first,
and writes no file if it is not valid.
