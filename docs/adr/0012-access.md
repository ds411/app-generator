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
  rule (ADR 0005) can add one. ADR 0018 adds owner rules.
- The menus of the front ends still show all pages. A page that the
  role may not open shows "not found". (The update below changes this.)
- The checks of the React app are a demonstration, not a protection.

### Update for M17: the front ends show only what the role allows

The front ends now hide the pages and the operations that the role of
the user does not allow (#274):

- One table of the permissions, `src/shared/lib/permissions.ts`, has
  the roles and the public parts. The checks of the pages and the
  operations and the UI read it. The pages have their names in the UI
  code (`roomDetail`).
- The hook `useAccess` gives the permissions of the signed-in user. The
  Next.js root layout reads the role on the server and gives it to the
  UI. The React app reads it from the session of the browser tab.
- A menu item shows only if the role may open its page or the page of
  one of its sub-items. A group of a menu shows only if one of its items
  shows. The page search shows only the pages that the role may open.
- A link to a page that the role may not open shows only its content,
  for example the title of a record in a table, without the link.
- An action shows only if the role may open its page and call its
  operation, for example the button of a form. A board does not move
  the cards for a role that may not call the update operation.
- A user without a session sees only the public pages and operations.
- A direct URL of a page that the role may not open still shows "not
  found", and the server (Next.js and FastAPI) checks each operation
  again.
- `scripts/check-auth-ui.sh` builds the room booking example with
  both front ends, signs in as a user of each role, and compares the
  menus with approved screenshots in the light and the dark mode.
