# 0031. Events of the entities

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

Many apps must do more work when a record changes: tell the organizer
when a booking is confirmed, compute a total again when a line changes,
or write an audit entry when a record is deleted. Without a place for
this work in the definition, each app developer adds the calls to each
endpoint that changes the record, and a new endpoint or a custom
operation can forget them.

The work of a change must be part of the change. If the work fails,
the change must not stay in the database, and the other way round.

The options for the place of the work:

- **Database triggers.** They run in the transaction of each change,
  also of a change that a script makes. But the logic is SQL, not the
  code of the app, and each database has its own trigger language.
- **The events of the ORM** (for example the session events of
  SQLAlchemy). They run on each flush. But they are synchronous, while
  the code of the apps is asynchronous, and a flush can contain many
  changes of many records.
- **A queue after the commit (an outbox).** The work runs later, in its
  own transaction. A failure of the work does not roll back the change.
  The jobs (ADR 0029) already give the apps work at a later time.
- **The data access functions of the apps.** The repository of each
  entity has the functions that create, change, and delete a record.
  The generated operations and the custom operations use them.

The work can start more changes, and each change can start more work.
Two events can start each other without end.

## Decision

An entity has the optional key `events`, with the changes `created`,
`changed`, and `deleted`. Each change names a custom operation of the
entity, for example `created: notify_owner`. `changed` can name
`fields`: then it runs only when one of these fields gets a new value.
Without `fields`, it runs when a stored field gets a new value. A
transition of a workflow has the optional key `run`, a custom operation
that runs after the transition.

We run the events in the repository functions: `add` (and so `create`),
`update`, and `delete`. The operation runs after the change is in the
database (a flush), in the transaction of the change, with the record.
After an update, the operations of the transitions run first, then the
operation of `changed`. An error of the operation rolls back the change
and all work of the operation.

In the operation of an event, a commit of a repository function only
writes the changes (a flush): the change that started the event
commits them. A change in the operation of an event starts no event:
the events stop after one level.

The app runs the operation without params, so the validator reports an
operation with a required param that has no default. The validator also
reports an operation of another entity, an unknown field in `fields`,
`fields` on `created` or `deleted`, and an operation that calls an API:
an event runs in a database transaction, and a call to a third-party
API does not belong in it.

The generated FastAPI tests turn off the events, so that the tests of
the other features do not depend on the logic of the operations. The
tests of the events of each entity replace the operations with fakes,
and check each kind of event, the rollback of a failed operation, and
the stop after one level. A test with the mark `events` runs the real
operations.

The Next.js app runs the operation in its repositories too, in the
transaction of the change: the repositories in the operation write in
that transaction. The repository of an entity (the entities layer)
imports the extension file of the operation (the features layer) only
when the event runs, because the operation imports the repository. The
mock store of the React app runs the operation after the change, as a
demonstration, without a transaction. With the FastAPI app, the React
app runs no event.

## Consequences

- The logic of an event is a custom operation, so it has one place, the
  extension file of the operation, and the API can also call it.
- The generated operations and the custom operations start the events,
  because both use the repository functions.
- A change outside the repository functions starts no event: a script
  with SQL, a delete that the database cascades to other records, or
  the seed of the database.
- An event that must start another event cannot: the work of the second
  event must be in the operation of the first one.
- A slow operation makes the change slow, and holds the locks of the
  transaction. Work that can wait belongs in a job (ADR 0029).
