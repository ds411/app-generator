# 0012. Roles and permissions

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

ADR 0011 closes the apps, but each signed-in user may do all. Many apps
have users with different rights, for example an admin who changes the
rooms and a member who only books them. ADR 0002 reserved the section
`access` for this.

The definition knows the operations and the pages, so a permission can
name them. A rule on single records (for example "only the owner may
change a booking") needs an expression language for conditions, and the
DSL does not have one for this.

## Decision

- The section `access` names an `enum` field of the user entity (the
  role field) and a list of roles. Each role is a value of the role
  field, and names its operations and pages, or `*` for all.
- The section needs `auth`. The public parts of `auth` stay open to all.
- FastAPI: a dependency `check_access` on each protected operation
  reads the role of the user and the operation ID of the route, and
  gives 403 if the role may not call the operation.
- Next.js: each protected page calls `requirePage`, which shows "not
  found" if the role may not open the page. Each protected server action
  checks the operation, and gives an error if the role may not call it.
- React: the same checks run in the browser with the mock users.
- The generated tests of the FastAPI app check the permission table, and
  call an allowed and a denied operation.

## Consequences

- The permissions are in the definition, and all apps use the same
  table.
- There is no rule on single records. A custom operation or a custom
  rule (ADR 0005) can add one.
- The menus of the front ends still show all pages. A page that the
  role may not open shows "not found".
- The checks of the React app are a demonstration, not a protection.
