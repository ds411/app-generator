# 0008. CRUD shorthand

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

Each CRUD operation of an entity is an explicit element of
`operations`. The project tracker has 4 entities, and 18 lines only
name the create, read, update, delete, and list operations. A simple
entity also needs a table view, a detail view, and two forms, which
repeat the fields of the entity.

The traces in the generated code refer to element IDs (ADR 0004). A
shorthand must give each element the same ID as the explicit form, or
the traces of hand-written code become invalid when an app author
changes from one form to the other.

We looked at these options:

- **Expand in the loader, before the model checks the data.** The
  model, the validator, the bindings, and the trace checker see only
  explicit elements.
- **Expand in the bindings.** Each binding must know the shorthand, and
  the trace checker cannot find the expanded elements.

## Decision

We add the key `crud` to an entity. The loader expands it in the plain
YAML data, before the model checks it:

- `crud: true` gives the five operations `create_<entity>`,
  `read_<entity>`, `update_<entity>`, `delete_<entity>`, and
  `list_<plural>`. `<entity>` is the entity name in snake case.
  `<plural>` comes from `plural_label` (for example `list_people`), or
  else from simple English rules (for example `list_categories`).
- `crud: [create, list]` gives some of the operations.
- The mapping form takes `operations` (default: all five), `views`
  (`table` gives `<entity>_table`, `detail` gives `<entity>_detail`),
  and `forms` (`create` gives `new_<entity>`, `update` gives
  `edit_<entity>`). The table has a column for each field (not `text`
  or `json`) and each `many_to_one` or `one_to_one` relation. The detail
  view has one section `details` with the fields and these relations.
  The forms have the fields and the relations that are not
  `one_to_many`.

An element that the definition gives explicitly, with the same name,
wins over the expanded element. The source location of each expanded
element is the `crud` key of its entity, so that the diagnostics point
to it. The `crud` key itself is not an element, so it is not in the
trace coverage.

## Consequences

- A definition is shorter: the project tracker loses its CRUD
  operation lines.
- The expanded elements have the IDs of the explicit form, so the
  generated code is the same, and the traces stay valid when an author
  changes from one form to the other.
- The expanded elements come before the explicit elements of the same
  mapping. A change from the explicit form can thus change the order
  of the operations, and the order of some generated code.
- An app author cannot see the expanded elements in the file. The
  names follow fixed rules, which the docs must describe.
- The default views and forms are plain. An app author who needs more
  writes the view or the form explicitly with the same name.
