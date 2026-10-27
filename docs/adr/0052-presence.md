# 0052. The other users on a record page

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

The live updates (ADR 0051) show the changes of other users in the open
views. But two users can change the same record at the same time, and
the second save wins. A user that sees the other users on the page of a
record, and sees when one of them types in a form, waits or talks to
them first.

The server must know which users have a page open, and tell the other
users at once. The options:

- **A heartbeat of each page, and the events of the live stream.** The
  page tells the server each few seconds that the user is on it, and
  the server sends the changes of the users on a record through the
  stream of ADR 0051. The server forgets a user without a heartbeat.
- **A WebSocket for each page.** The connection itself tells that the
  user is on the page. But the apps have no WebSocket server, and
  ADR 0051 chose server-sent events for the same reasons.
- **The open streams.** A stream ends when its page closes. But one
  stream serves all pages of a browser tab, and with replicas the
  stream and the calls of a page go to different processes.

The state of a page is small and short. A store in the database would
give a write for each heartbeat.

## Decision

A page takes `presence: true`. The page shows the record of a detail
view, its path ends with `{id}` and has no other parameter, the entity
of the view is live (`entities.*.live`, ADR 0051), and the app has
`auth`. The page is not in `auth.public_pages`. The validator reports
the other cases.

The page shows the avatars of the other signed-in users on the pages of
the same record: the initials of the name of each user, with the name
as its text for a screen reader and as its tooltip. When a user types in
a field of a form on the page, for example in the form of the button
"Edit", the other users see the note "<name> is typing.". The name of a
user is the display field of the user entity, else the user name.

The page calls the server when it opens, when the user starts or stops
to type, and each 5 seconds (the heartbeat). A user stops to type 3
seconds after the last input. When the page closes, it tells the server
that the user left. The server forgets a user 15 seconds after the last
heartbeat, for example after a crash of the browser.

The FastAPI app has these endpoints for each entity with a page with
`presence`:

- `PUT /<entity>/{id}/presence` with `{"typing": false}`: the user is
  on the page of the record. The answer has the other users on the
  record: `{"users": [{"id", "name", "typing"}]}`.
- `DELETE /<entity>/{id}/presence`: the user left.

Both need the permission of a read operation of the entity and its
record rules (ADR 0025), as `GET /<entity>/{id}`: a record that the user
may not read gives 404. The Next.js app has server actions with the
same checks. The React app with the FastAPI app calls the endpoints.

The broker of the live updates keeps the users on each record, in the
memory of the process. A change of the users on a record (a new user, a
start or a stop of the typing, a user that left or that the server
forgot) gives the event `presence` with the entity, the ID, and the
users, to the streams of the other users on the record. Only these
users get it: they called the endpoint, so they may read the record.
Each stream gets the users without its own user. With
`LIVE_EVENTS_URL`, the brokers send the heartbeats through the Redis
channel of the live updates, so that each replica knows the users of
all replicas. Each replica forgets the users by itself.

An answer of the endpoint that left before the last event is older than
the event, so the page keeps the users of the event.

## Consequences

- The users of a record see each other, and the users that type, in
  about 1 second, also on other replicas with Redis.
- The users on a record see the names of each other, also a user that
  may not read the user entity.
- After a crash of the browser, the other users see the user for 15
  to 20 seconds more.
- A user that loses the access to a record still gets its events
  `presence` until the server forgets the user, at most 15 seconds.
- A new replica, and a replica after a loss of Redis, knows the users
  on a record only after their next heartbeats, at most 5 seconds.
- The state is in memory: a stop of the process forgets it, and the
  next heartbeats give it again.
- The React app with mock data shows no users: it has no server, and
  each browser has its own data.
