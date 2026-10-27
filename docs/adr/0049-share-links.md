# 0049. Secret links that share a record

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

A page of an app with `auth` is for the users with an account. A page
in `auth.public_pages` is open to all persons, for all records. Many
apps give one record to a guest: a document, an invoice, or a report
goes to a person without an account, with a link. The other records
stay closed.

The options for the link:

- **A signed token** (the ID of the record and a signature, as in the
  links of the password reset). The app keeps nothing. But the app
  cannot revoke one link: only a change of the signing key revokes all
  links.
- **A random token in a table.** The app keeps each link, and a delete
  of the row revokes it. The table can keep the hash of the token only,
  as for a password, so that a copy of the database gives no links.
- **A guest account for each link.** The guest signs in. It is too much
  for one record.

A guest sees the record and the related records that the page shows,
for example the course of a lesson. The guest may not read the lists of
the entities, so the server must give the related records with the
record.

## Decision

A page takes `share: true`. The page is a detail page: its content is a
detail view, its path ends with `{id}` and has no other parameter, and
its entity has an update operation. The app has `auth`, the page is not
in `auth.public_pages`, and it has no `embed`. An entity has one page
with `share` at most. The validator reports the other cases.

A link opens the shared page of the record: `/shared` and the path of
the page, with the token in the place of `{id}`, for example
`/shared/lessons/{token}`. The validator reports a page with the same
path.

The apps keep one table `share_links` for all entities. A row has an
ID, the entity, the ID of the record, the hash of the token (SHA-256,
hexadecimal), the ID of the signed-in user that made the link (or
none), and the time. A record has one link at most. A token has 32
random bytes, in base64url without padding. The app gives the token one
time only, when it makes the link: a later read of the link gives only
its time. A new link replaces the old link, and a revoke deletes the
row. The rows have no foreign key, as the entries of the change log
(ADR 0040): a link of a deleted record opens nothing.

The FastAPI app has these endpoints for each entity with a shared page:

- `GET /<entity>/{id}/share`: the state of the link of the record
  (`active`, `created_at`).
- `POST /<entity>/{id}/share`: a new link. The answer has the token.
- `DELETE /<entity>/{id}/share`: a revoke.
- `GET /shared/<entity>/{token}`: the record, and the related records
  that the detail view shows (`related`, by the name of the entity).
  This endpoint is public.

Only a user that may change the record makes, reads, and revokes its
link: the first three endpoints need the permission of the update
operation, and its record rules of a change. A wrong token, a revoked
token, and the token of a deleted record give status 404, with the
same answer.

The Next.js app keeps the same table, and has server actions with the
same checks. The mock store of the React app keeps the links in the
local storage of the browser, so that a link opens in another tab of
the same browser. The React app with the FastAPI app calls the
endpoints.

The detail page has a button "Share" in its header for a user that may
call the update operation. The button opens a dialog: it makes a link
and shows it one time, with a copy button, and it makes a new link or
revokes the link. The shared page shows the detail view without the app
shell and without the actions. It does not show the tabs of the lists
of the related records and of the change log, because the guest may not
read them.

## Consequences

- An app author shares a record without a public page and without an
  account for the guest.
- The guest gets all fields of the read schema of the record, with its
  embedded records, and of the related records that the view shows, in
  the answer of the endpoint. The record rules of the roles (ADR 0025)
  do not hide an embedded record from a guest, because a guest has no
  role. An author that does not want a value in a link keeps it in
  another entity.
- A link does not expire. The owner revokes it, or makes a new link.
- The token shows one time only. A user that loses the link makes a new
  link, and the old link stops.
- A link of a new record of the React app with mock data opens only
  until a reload of the app, because the mock store forgets the new
  records.
