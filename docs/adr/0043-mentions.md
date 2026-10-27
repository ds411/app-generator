# 0043. Mentions of users in a text

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

A comment, a note, or a description often asks a colleague for help.
Many apps let the author write `@` and the name of a user: the text
shows the name as a link, and the user gets a notice. The notices of
ADR 0041 come from the notifications of the definition: a change of
named fields, and receivers on paths of relations. A mention is not a
relation: the users come from the text itself.

The options for the form of a mention in the stored text:

- **The user name, for example `@ann`.** The text is easy to read in
  the database and in the API. But the apps must find the user of each
  name for each view of the text, and a user name can change or have
  spaces.
- **The display value and the ID, for example `@[Ann Lee](<ID>)`.** The
  views need no search for the link, and a later change of the name does
  not break the mention. The raw text in the API and in an export holds
  the IDs.

## Decision

A `text` field takes `mentions: true`. It needs `auth`: the users are
the records of the user entity. A computed or a translatable text cannot
have mentions. The validator reports the other cases.

A mention in the stored text is `@[<display value>](<ID of the user>)`.
The display value has no brackets and no line breaks.

- The form widget of the field is a text area. After `@` at the start
  of a word, a list suggests the users whose display value has the text
  after the `@`, as a relation field to the user entity does: the
  records in the browser, or a search of the server with
  `x-react-data: api`. A choice puts the mention into the text.
- The views show a mention as `@` and the display value, with a link to
  the first page with a detail view of the user entity, if one exists.
- A create or a change of a record gives a notice to each user that the
  new text mentions and the text before did not, with the built-in
  notification `@mention`, in the transaction of the change (ADR 0041).
  A notification of the definition cannot have this name. The text of
  the notice is "You are mentioned in {record}.", with the display value
  of the record. A mention of an ID without a user, and a mention of the
  user that made the change, give no notice.

The FastAPI and the Next.js apps add the notices in the repository
functions, as the notices of the notifications. The React app with mock
data adds them in the mock store.

## Consequences

- An author adds mentions with one key, without a relation and without
  a notification.
- The raw text in the API, in a CSV export, and in a search has the
  IDs of the users. A client of the API writes a mention in the same
  form.
- A mention keeps the display value of the time of the mention. A later
  change of the name of the user does not change the text.
- The list of the users needs the permission of the list of the user
  entity, as a relation field to it does. Without it, the list is
  empty, and the author can still type a mention by hand.
- A user that a text mentions gets a notice, also without the
  permission to read the record. The link of the notice then opens a
  page that shows an error.
