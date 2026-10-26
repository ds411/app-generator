# 0040. Change log of the records

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

The apps keep only the current state of each record. Many apps show who
changed a record, when, and what the values were before: the history of
an issue, the history of a page, or an audit log. A user that makes a
wrong change wants the old values back.

The options for the place of the log:

- **Database triggers.** They see each change, also a change of a
  script. But they do not know the user of the request, and each
  database has its own trigger language.
- **A copy of the record for each version** (a history table for each
  entity, with all columns). A restore of a version is simple. But each
  change of the schema of an entity must change its history table too,
  and the log does not show which fields changed.
- **One table of entries for all entities.** Each entry has the entity,
  the record, the user, the time, and the old and the new value of each
  field that changed, as JSON. A change of the schema of an entity does
  not change the table.

The events (ADR 0031) run in the data access functions of the apps,
which the generated and the custom operations both use. The log needs
the same place, so that no operation forgets it.

## Decision

An entity has the optional key `history`: `true`, or a mapping with
`fields` and `description`. The log keeps the stored fields except the
file fields, and the `many_to_one` relations (the ID of the target).
`fields` names some of them. A translatable field keeps the value of
the default language. The validator reports a name in `fields` that is
not such a field or relation.

The apps keep one table `history_entries` for all entities. An entry
has an ID, the entity, the ID of the record, the action (`created`,
`changed`, `deleted`, or `restored`), the ID of the signed-in user (or
none), the time, and the changes: a mapping from the name of each field
in the definition to its old and its new value, as JSON. A decimal
number, a date, a time, and an ID are text: a time in UTC, and a
decimal number without the zeros at the end, so that the same value
gives the same text.

The repository functions `add`, `update`, and `delete` add the entry in
the transaction of the change, after the events, so that the changes of
the operations of the events are in the entry. A change without a new
value adds no entry. The entries stay after the delete of a record, and
have no foreign key to the record or to the user.

The FastAPI app has two endpoints for each entity with a log:
`GET /<entity>/{id}/history` gives a page of the entries of a record,
the newest first, with the display value of the user, and
`POST /<entity>/{id}/history/{entry_id}/restore` gives the fields of an
entry of a change their old values back. The entries of a record need
the permission of the read operation of the entity, and its record
rules of a read. The restore is a change: it needs the permission of
the update operation, and it goes through `update`, with its checks:
the validation, the rules, the workflows, the record rules, and the
events. It adds an entry `restored`. An entry of a create or of a
delete has no old values to restore. Without a read operation, the
entries have no endpoint, and without an update operation the restore
has none.

The dependency of the signed-in user puts the ID of the user in the
session of the request, and the entry takes it from there. A change
without a request, for example in a job, has no user.

The Next.js app and the UI of the front ends follow in their own story.

## Consequences

- The generated and the custom operations add the entries, because
  both use the repository functions. A change outside these functions
  adds none: SQL in a script, a record that the database deletes with
  `on_delete: cascade`, and the seed.
- The log shows only the fields that changed. A restore gives back the
  old values of one entry, and keeps the later changes of the other
  fields.
- A restore can fail: a workflow can forbid the old state, and the old
  target of a relation can be deleted.
- The table grows with each change. The apps do not remove old entries:
  a job can do it.
- A change of the name of a field in the definition does not change the
  old entries: they keep the old name, and a restore skips the names
  that the log does not keep now.
