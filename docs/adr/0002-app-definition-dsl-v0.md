# 0002. App definition DSL v0

- Date: 2026-10-23
- Deciders: Maintainers

## Status

Accepted

## Context

The generator reads an app definition and writes the code of an app
for one or more bindings. The app definition is a YAML file. Version 0
of the DSL describes the data model and the pages of an app: the app,
its entities, their fields and relations, the operations, and the
pages. The UI part of the DSL (design tokens, layouts, views, and
forms) gets its own ADR in M2.

Authentication, authorization, workflows, and translations are out of
scope for version 0. We must be able to add them later without a
breaking change to the definitions that exist.

Traces in the generated code refer to the elements of the definition.
Thus each element needs an ID that is stable when other elements
change.

We looked at similar DSLs:

- **JHipster JDL** is a custom language with entities, fields,
  relationships, and options. Relations are declared in a separate
  `relationship` block, by kind (`OneToMany`, `ManyToOne`, ...). A
  custom grammar needs a custom parser, an editor plugin, and its own
  error messages.
- **The Prisma schema** is a custom language too. It declares
  relations as fields with a `@relation` attribute, and it needs a
  field on each side of a relation. Field types are a short, fixed
  list of scalars plus enums.
- **Amplication** keeps entities, fields, and relations in a database
  and shows them in a web UI. It exports JSON. Field types are
  semantic (for example `Email`, `Lookup`, `OptionSet`), not only
  storage types.
- **OpenAPI** is YAML or JSON with a JSON Schema. It reserves keys that
  start with `x-` for vendor extensions.

## Decision

### Format

We use YAML. YAML needs no custom parser, editors check it with a JSON
Schema (#12), and it allows comments, unlike JSON. One file holds one
app definition. The loader reads YAML 1.1 with the safe loader of
PyYAML, and keeps the line and the column of each key and value.

### Top-level sections

| Key          | Required | Content                                                  |
| ------------ | -------- | -------------------------------------------------------- |
| `version`    | Yes      | The DSL version, an integer. Version 0 is `0`.           |
| `app`        | Yes      | The name, the title, and the description of the app.    |
| `entities`   | Yes      | A mapping from entity name to entity.                    |
| `operations` | No       | A mapping from operation name to operation.              |
| `pages`      | No       | A mapping from page name to page.                        |

These keys are reserved for later versions: `ui`, `auth`, `access`,
`workflows`, and `translations`. In version 0, the loader reports
"not supported in this version" for each of them.

### Mappings, not lists

Each collection of named elements is a YAML mapping from the name to
the element, not a list of elements with a `name` key. A mapping gives
each element a unique key, and the key is part of the element ID. A
new element, or a change of order, does not change the ID of other
elements.

### Names

| Element                       | Rule                     | Example        |
| ----------------------------- | ------------------------ | -------------- |
| App name                      | `^[a-z][a-z0-9-]*$`      | `project-tracker` |
| Entity                        | `^[A-Z][A-Za-z0-9]*$`    | `Task`         |
| Field, relation, param        | `^[a-z][a-z0-9_]*$`      | `due_date`     |
| Operation, page               | `^[a-z][a-z0-9_]*$`      | `complete_task` |
| Enum value                    | `^[a-z][a-z0-9_]*$`      | `in_progress`  |

The bindings convert the names to the conventions of their language,
for example `dueDate` in TypeScript. Names cannot contain a dot, so a
dot can separate the parts of an ID. The name `id` is reserved for
fields and relations: each entity has an implicit primary key `id`.

### Entities

An entity has these keys:

- `description`: optional text.
- `label` and `plural_label`: optional display names. The default
  comes from the entity name.
- `display_field`: optional. The field that shows a record in a list
  or a reference, for example `name`.
- `fields`: a mapping from field name to field. Required, with one or
  more fields.
- `relations`: an optional mapping from relation name to relation.

Each entity has an implicit primary key `id` of type `uuid`. The
definition does not declare it.

### Field types

| Type       | Meaning                                  | Options                                 |
| ---------- | ---------------------------------------- | --------------------------------------- |
| `string`   | A short line of text.                    | `min_length`, `max_length`, `pattern`   |
| `text`     | Long text with line breaks.              | `min_length`, `max_length`              |
| `integer`  | A whole number.                          | `min`, `max`                            |
| `decimal`  | An exact decimal number.                 | `min`, `max`, `precision`, `scale`      |
| `boolean`  | True or false.                           |                                         |
| `date`     | A calendar date.                         |                                         |
| `datetime` | A date and time with a time zone.        |                                         |
| `uuid`     | A UUID.                                  |                                         |
| `email`    | An email address.                        | `max_length`                            |
| `url`      | A URL.                                   | `max_length`                            |
| `enum`     | One value from a fixed list.             | `values` (required)                     |
| `json`     | A JSON value.                            |                                         |

All fields also take `description`, `label`, `required` (default
`false`), `unique` (default `false`), and `default`. Like Amplication,
`email` and `url` are semantic types: a binding can store them as text
and still check them and show them in a better way.

### Relation kinds

| Kind           | Meaning                                               | Foreign key           |
| -------------- | ----------------------------------------------------- | --------------------- |
| `many_to_one`  | Many records of this entity refer to one target.      | On this entity.       |
| `one_to_many`  | One record of this entity has many target records.    | On the target entity. |
| `one_to_one`   | One record of this entity refers to one target.       | On this entity.       |
| `many_to_many` | Many records on each side.                            | In a join table.      |

A relation has these keys: `kind` and `target` (both required),
`description`, `label`, `required` (for `many_to_one` and `one_to_one`
only), `inverse`, and `on_delete` (`restrict`, `cascade`, or
`set_null`, for `many_to_one` and `one_to_one` only).

`inverse` names the relation on the target that is the other side.
A `one_to_many` relation must have an `inverse`, which is a
`many_to_one` relation on the target back to this entity. Unlike
Prisma, the other side is optional for the other kinds. Unlike JDL,
each relation belongs to its entity, so its ID is under the entity.

### Operations

An operation is an action that an app can do on an entity. It has
these keys:

- `kind`: `create`, `read`, `update`, `delete`, `list`, or `custom`.
- `entity`: the entity that the operation works on.
- `description`: optional text.
- `params`: custom operations only. A mapping from parameter name to
  a field (the same keys as an entity field).
- `returns`: custom operations only. An entity name, or `none` (the
  default).

The bindings generate the code of the CRUD and list operations. The
logic of a custom operation is a generation gap: the binding generates
the signature, and hand-written code in an extension file gives the
body.

### Pages

A page is a screen of a front-end app. It has these keys:

- `path`: the URL path, for example `/projects/{id}`. Required.
- `title`: required.
- `entity`: optional. The main entity of the page.
- `description`: optional text.

Version 0 only declares the pages. The UI ADR (M2) adds the content of
a page.

### Element IDs

Each element has an ID. Traces in the code use the ID to refer to the
element. The ID is the path of mapping keys from the root of the
definition to the element, with a dot between the keys:

```text
id      = segment *( "." segment )
segment = name                ; a mapping key, see "Names"
```

| Element   | ID                                          |
| --------- | ------------------------------------------- |
| App       | `app`                                       |
| Entity    | `entities.<Entity>`                         |
| Field     | `entities.<Entity>.fields.<field>`          |
| Relation  | `entities.<Entity>.relations.<relation>`    |
| Operation | `operations.<operation>`                    |
| Param     | `operations.<operation>.params.<param>`     |
| Page      | `pages.<page>`                              |

An ID never contains a list position. A rename of an element changes
its ID, and the trace checker (M4) then reports the traces to the old
ID. Later sections follow the same rule, for example
`ui.tokens.color.primary`.

### Extensions

A key that starts with `x-` is an extension key, as in OpenAPI. The
root of the definition and each element (a mapping with fixed keys, for
example the app, an entity, or a field) can have extension keys. A
mapping of named elements, for example `entities` or `fields`, cannot
have them, because each of its keys is a name. The loader keeps the
extension keys and does not check them. Any other unknown key is an
error.

### Example

```yaml
version: 0

app:
  name: project-tracker
  title: Project Tracker

entities:
  Project:
    display_field: name
    fields:
      name: { type: string, required: true, max_length: 120 }
      status:
        type: enum
        values: [planned, active, done]
        default: planned
    relations:
      tasks: { kind: one_to_many, target: Task, inverse: project }

  Task:
    display_field: title
    fields:
      title: { type: string, required: true }
      due_date: { type: date }
      done: { type: boolean, default: false }
    relations:
      project:
        kind: many_to_one
        target: Project
        required: true
        on_delete: cascade
        inverse: tasks

operations:
  create_task: { kind: create, entity: Task }
  list_tasks: { kind: list, entity: Task }
  complete_task:
    kind: custom
    entity: Task
    params:
      note: { type: text }
    returns: Task

pages:
  projects: { path: /projects, title: Projects, entity: Project }
```

### How the out-of-scope features fit in later

Each feature gets a reserved top-level section. A later version adds
the section as an optional key, so that the definitions that exist
stay valid. The new sections refer to the version 0 elements by name or
by ID.

| Feature        | Section        | Plan                                                                                                   |
| -------------- | -------------- | ------------------------------------------------------------------------------------------------------ |
| UI             | `ui`           | M2: design tokens, layouts, navigation, views, and forms. Pages refer to them.                         |
| Authentication | `auth`         | Identity providers and the entity that holds the users, for example `user_entity: Person`.             |
| Authorization  | `access`       | Roles, and rules that give a role access to operations and pages by ID, for example `operations.delete_task`. |
| Workflows      | `workflows`    | State machines on an `enum` field: states are its values, and transitions refer to custom operations.  |
| Translations   | `translations` | A mapping from locale to messages. A message key is an element ID and a property, for example `entities.Task.fields.title.label`. |

If a feature also needs keys on the elements of version 0 (for
example, a field that only one role can see), the new key is optional,
and its default keeps the behavior of version 0. Until then, an app
author can use an `x-` key to hold such data for a custom binding.

### Versions

`version` is the major version of the DSL, an integer. A change that
only adds optional keys or sections keeps the version. A change that
can make a valid definition invalid, or that changes the meaning of a
key, increases the version, and needs a new ADR. The loader rejects a
version that it does not know.

## Consequences

- A YAML file needs no custom parser, and editors complete and check
  it with the JSON Schema. JDL and Prisma need their own tools for
  this.
- Mappings give stable IDs, so traces stay valid when the definition
  grows. The order of the elements in the output comes from the
  mapping order in the file, which is deterministic.
- YAML has pitfalls: for example YAML 1.1 reads `no` and `on` as
  booleans. An enum value such as `on` must have quotes. The name
  rules and the schema reject a boolean where a name must be.
- CRUD operations are explicit, so a definition with many entities is
  long. A later version can add a shorthand, as an optional key.
- A rename changes an ID and breaks the traces to the old ID. The trace
  checker reports these traces, so that the developer can fix them.
- Reserved sections and `x-` keys let us add features without a
  breaking change. The cost is a loader that must know the reserved
  names, and extension data that the loader does not check.
