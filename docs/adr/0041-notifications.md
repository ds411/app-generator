# 0041. Notices of the changes of records

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

The users of an app want to know about the changes that concern them:
a task that a colleague gives them, a booking that an administrator
moves, an issue that changes its state. Many apps show these changes
as notices with a bell, and send some of them by email.

The apps already run code after a change of a record: the events
(ADR 0031) run a custom operation in the transaction of the change, and
the change log (ADR 0040) adds its entries there. An event can send a
notice, but each app author must then write the same logic again: who
gets the notice, its text, and its storage.

The options for the definition of the receivers:

- **A role or a list of users.** Simple, but a notice for "the
  assignee of the task" or "the members of the team of the project"
  depends on the record.
- **A path of relations from the record to the users.** The record
  rules (ADR 0025) already use such paths for the owner of a record,
  with the same checks: each step is a many-to-one or a many-to-many
  relation, and the last step goes to the user entity.

The options for the text:

- **The text with its values at the time of the change.** One text,
  in the language of the user that made the change.
- **The name of the notification and the values.** The API gives the
  text in the language of the user that reads it.

## Decision

The definition has the optional section `notifications`. It maps a
name to the entity, the change, the receivers, and the text:

- The change is `event: created`, `event: changed` (with `fields`: the
  stored fields and the `many_to_one` relations that it watches, all of
  them by default), or `transition`: a transition of a workflow of the
  entity, `<transition>` or `<workflow>.<transition>`.
- `receivers` are paths of relations to the user entity of `auth`,
  with the rules of the owner paths of the record rules. A notification
  needs `auth`.
- `text` has the values of the record in braces: a stored field, or a
  `many_to_one` relation (the display value of its record).

The validator reports a notification without `auth`, a change that does
not exist, `fields` without `event: changed`, a receiver path that does
not end at the user entity, and a value in braces that is not a stored
field or a `many_to_one` relation.

The FastAPI app keeps the notices in the table `notices`: the user that
gets the notice, the name of the notification, the entity and the ID of
the record, the user that made the change, the values of the text as
text, the time, and the time of the read. The repository functions
`add` and `update` add the notices in the transaction of the change,
after the events and the change log. Each user at the end of a receiver path gets one notice, except the
user that made the change. The notices of a deleted user go with the
user, and the notices of a deleted record stay.

The text of a notice is a key of the translations. `GET /notices`
gives the notices of the signed-in user, the newest first, with the
text in the language of the request, and `unread=true` gives only the
unread notices. `POST /notices/{id}/read` marks one notice read, and
`POST /notices/read` all notices of the user.

The Next.js app keeps the notices in the same table `notices`, and its
repositories add them in the transaction of the change, as the FastAPI
app does. The server actions give the notices of the signed-in user and
mark them read. The React app with mock data keeps the notices in the
session storage of the browser tab, so that a user that signs in after
the change sees them. With `x-react-data: api`, the React app reads them
from the FastAPI app.

The top bar of a layout, and the header of the pages without a layout,
show a bell: the count of the unread notices of the signed-in user, and
a list of the newest notices. Without a signed-in user, the bell does not
show. The front ends
write the text of a notice from the name of the notification and the
values, in the selected language. A click on a notice marks it read and
opens the detail page of its record: the first page with a detail view
of the entity and one parameter in its path.

## Consequences

- The generated and the custom operations both give the notices,
  because both use the repository functions. A change outside these
  functions gives none: SQL in a script, and the seed.
- A notice keeps the values of its text from the time of the change. A
  later change of the record does not change the text of the notice.
- A notification with a path through a many-to-many relation reads the
  database in the transaction of the change: each such path is one
  query for each step.
- The table grows with each notice. The apps do not remove old notices:
  a job can do it.
- A notification without users at the end of its paths gives no
  notice. The validator cannot see that.
- The bell loads the notices again when the page changes, when it
  opens, and after a read. A notice of a change by another user shows
  after the next page change: the apps do not push the notices to the
  browser.
- The React app with mock data shows the notices of the changes in the
  browser tab only. The records go back to the mock data when the page
  reloads, so the record of a notice can have its old values again.
