# 0018. Owner rules for single records

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

A role allows operations and pages (ADR 0012), but it cannot limit a
user to some records. In the room booking example, a member can read and
change the bookings of all members. A general rule on records needs an
expression language for conditions, and the DSL has none for this.

The usual need is simpler: a user uses only the records that the user
owns. An entity with a relation to the user entity knows the owner of
each record.

## Decision

- A role can have owner rules: `access.roles.<role>.records.<entity>`
  with `owner`, a many-to-one relation of the entity to the user entity,
  and `operations`: `read`, `change`, or both (the default).
- `read` applies to the lists and the reads. `change` applies to the
  creates, the changes, the deletes, and the custom operations. A rule
  for `read` also applies to the changes, because a user cannot change
  a record that the user cannot see.
- All rules of an entity use the same relation, so that the code of the
  entity has one filter. A rule does not apply to the public operations.
- FastAPI: the repository of the slice has the filter (`owned`, and an
  `owner` argument of `get`, `add`, `create`, and `update`), so that each
  query of an operation uses it. A dependency (`owner_of`) gives the
  owner of a request: the signed-in user if a rule of the role applies,
  else nobody. A list gives only the records of the owner. A read, a
  change, a delete, or a custom operation on another record gives 404,
  not 403, so that a caller cannot find the IDs of other records. A
  create sets the owner to the user, and a change cannot give the
  record to another user.
- The rules of the entities (for example "no double booking") still see
  all records.
- The front ends read the rules from the shared table of the
  permissions (`src/shared/lib/permissions.ts`, ADR 0012).
  - Next.js: the repository has the filter (an `owner` argument of
    `list`, `exists`, `get`, `update`, and `remove`), and the server
    actions give it the user if a rule of the role applies
    (`recordOwner`). A create and a change set the owner to the user. A
    detail page and a custom operation on a record of another user give
    "not found", as in FastAPI.
  - React with the FastAPI app: the API applies the rules. React with
    mock data: the mock store applies them in the browser, as a
    demonstration, as the other checks of the roles in a mock app.
  - The forms of a create or a change do not show the owner field to a
    user of a rule, and set its value to the user (`ownerOf` of the hook
    `useAccess`). The server sets the owner again.

## Consequences

- The definition can express "each member sees only the bookings of the
  member" without code.
- A rule cannot use other conditions, for example a team or a status. A
  custom operation or a custom rule (ADR 0005) can add them.
- An embedded relation (`x-fastapi-embed`) of another entity can still
  show a record of another user. The owner rule applies to the
  endpoints of the entity itself.
- A user of a rule cannot give a new record to another user in the UI,
  because the form does not show the owner field. A role without a rule
  (for example an admin) sees the field.
