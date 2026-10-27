# 0050. Records of guests that move to the user

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

A shop lets a visitor fill a cart before the sign-up. The items of the
cart are records, but a visitor without a sign-in has no user record,
and a public operation (`auth.public_operations`) has no owner: each
visitor would see the records of all visitors. After the sign-up or the
sign-in, the visitor expects to find the cart.

The options for the owner of the records of a visitor:

- **A user record for each visitor.** The user entity needs a user name
  and the other required fields. The visitors fill the table of the
  users, and the move at the sign-in merges two users.
- **A guest ID in a column of each record.** A signed guest token holds
  a random guest ID. The app keeps no table of the guests: the records
  of a guest have its ID. The move sets the owner relation and clears
  the guest ID.
- **The records in the browser only.** The front end keeps the cart,
  and makes the records after the sign-in. Each front end needs its own
  copy of the logic, and the API has no records of the guests.

## Decision

`auth.guests` names the entities whose records a guest can own, with
the owner relation of each: a many-to-one relation to the user entity
that is not required. `operations` names the operations that a guest
may call: list, read, create, update, and delete operations of these
entities, not public. `token_days` (default 30) is the time of a guest
token. The guests need `access`: the roles of the signed-in users. An
entity of the scope of the memberships (ADR 0048) cannot be an entity
of the guests. The validator reports the other cases.

The FastAPI app:

- `POST /auth/guest` gives a guest token: a signed text with a new
  random guest ID, the purpose `guest`, and the end of its time. A
  guest token is not valid as the token of a user, and the token of a
  user is not valid as a guest token. The app stores nothing.
- Each entity of the guests has the column `guest_id`, with an index.
  The read and the input schemas do not have it.
- A request of a guest operation with a guest token in the header
  `Authorization` passes the check of the roles. The records of the
  request are the records with the guest ID of the token (`GUEST_RULE`
  in `app/core/access.py`). A new record of a guest gets the guest ID
  and no owner, and a change of a guest cannot set the owner. A guest
  has no record rule for the other entities, as a public operation: for
  example for the embedded records. A request of a guest operation with
  the token of a user has the record rules of the role of the user.
- `POST /auth/guest/move` with a guest token gives the records of the
  guest to the signed-in user: the owner relation of each record is the
  user, and the guest ID is cleared. The answer has the number of the
  records. A guest token that is not valid, or that has ended, gives
  400. The move is one endpoint for all ways to sign in: with a
  password, with a second factor, with a provider, and at the sign-up.
  The front ends call it after each sign-in.

The generator stops with an error if an entity of the guests has a
member `guest_id`, or if an operation has the operation ID
`start_guest_session` or `move_guest_records`.

The Next.js app and the React app get the guests in a later change.
Until then, the trace check reports `auth.guests` as a gap in these
apps.

## Consequences

- A visitor fills a cart without a sign-in, and keeps it after the
  sign-up: an app author names the entity and its owner relation.
- The move changes only the owner and the guest ID, with one update for
  each entity. It runs no rules, no events, and no change log entry
  (ADR 0040).
- A guest token that ends leaves its records in the database, without
  an owner and without a way to reach them. A job of the app can delete
  the old records of the guests.
- A person with the guest token of another visitor has the records of
  that guest, as with the token of a user. The front ends keep the
  token as they keep the token of a user.
- A guest calls only its guest operations: the files, the change log,
  and the other endpoints of the entities need a user.
