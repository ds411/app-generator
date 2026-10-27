# 0051. Live updates of the records

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

The views of the apps show the records at the time of their load. When
two users work on the same records, for example on a task board, a user
sees the changes of the other user only after a reload. Many apps show
the changes at once.

The options for the transport:

- **Polling.** The client reads the list again each few seconds. It is
  simple, but it sends many requests without a change, and a change
  comes late.
- **WebSockets.** A connection in two directions. The live updates need
  only one direction, from the server to the client. A WebSocket needs
  its own authentication and its own proxy settings.
- **Server-sent events.** A long HTTP response of the server, with one
  event for each change. The browser API `EventSource` connects again
  after a loss. The response goes through the HTTP proxies, and FastAPI
  0.161 has a response class for it.

The options for the content of an event:

- **The record.** The client does not read it again. But the server
  must give each user the fields that the user may read, with the
  language of the user and the computed values: the same work as the
  read operation, for each client.
- **The entity, the ID, and the action.** The client reads the record
  again with the operations of the entity, with their access rules
  (ADR 0012, ADR 0025). An event costs one request for each open view.

The changes come from the generated and the custom operations, the
events (ADR 0031), the jobs (ADR 0029), and the restores of the change
log (ADR 0040). An API runs as more than one replica (ADR 0013): a
change on one replica must go to the clients of all replicas.

## Decision

An entity has the optional key `live`: `true`, or a mapping with
`description`. The validator reports an entity with `live` and without
a list or a read operation (`missing-key`).

The FastAPI app has the endpoint `GET /live`: a stream of server-sent
events. The first event is `open`. Each create, change, and delete of a
record of a live entity gives an event with its type (`created`,
`changed`, or `deleted`), the entity, and the ID of the record, after
the commit of the transaction. The event has no values. The query
parameter `entity` selects the entities, and the default is all the
live entities that the client may read.

- **The changes.** Listeners of the SQLAlchemy sessions find the
  changes at each flush, and keep them until the commit. A rollback
  drops them. A create and a delete in one transaction give no event,
  and more changes of one record give one event. So all the code that
  writes through a session of the app gives the events.
- **The access.** A client may open the stream of an entity if its role
  may call a list or a read operation of the entity (ADR 0012). Else
  the stream gives 401 without a user, and 403 with a user. With a
  record rule for the reads of the entity (ADR 0025), each change keeps
  the audiences of the record before and after the change: the roles
  whose rule conditions the record meets, and the users at the end of
  the owner path. A client gets the event if its role and its user are
  in one of the audiences. So a user sees the change that moves a
  record out of the view of the user, but not the changes of records
  that the user may not read. A public operation gives the events to
  all clients.
- **The replicas.** Without the setting `LIVE_EVENTS_URL`, each process
  gives the changes of its own transactions to its own streams. With a
  Redis URL in `LIVE_EVENTS_URL`, each process sends its changes to a
  Redis channel, and gives the changes of the channel to its streams.
  The worker of the jobs sends its changes to the channel too. When
  Redis is not available, a process logs a warning and gives its own
  changes to its own streams. When Redis comes back, each stream gets
  `reset`, because it can have lost events.
- **A slow client.** Each stream keeps at most 100 events. With more,
  the stream drops them and sends `reset`. After `reset`, and after a
  new connection, the client reads its open views again.
- **The stop of the server.** A server waits for the open requests
  before it stops, and a stream does not end by itself. At SIGINT and
  SIGTERM, the app ends its streams, and then calls the signal handler
  of the server. The clients connect again, for example to another
  replica.

The Next.js app and the React app use the same events to read their
open views again.

## Consequences

- The open views show a change in less than a second, also the changes
  of other replicas through Redis.
- An event costs a read of the record for each open view. A view reads
  only what its user may read, with the usual checks.
- A change outside the sessions of the app gives no event: SQL in a
  script, a record that the database deletes with `on_delete: cascade`,
  and an `update` or a `delete` statement of many records.
- Without Redis, a change of another replica or of the worker gives no
  event. An app with more than one replica needs `LIVE_EVENTS_URL`.
- Redis pub/sub does not keep the events: a client that is not
  connected loses them, and reads its views again after the new
  connection.
- A platform with a time limit for each request, for example Cloud Run,
  closes the streams at that limit. The clients connect again.
- An open stream holds a connection of the server, but no connection of
  the database.
