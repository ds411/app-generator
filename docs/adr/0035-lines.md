# 0035. Lines of a record in create and update operations

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

Many records have lines: an invoice has invoice lines, an order has
order items, and a journal entry has debits and credits. The lines are
the records of a `one_to_many` relation. An operation edited one record,
so a client wrote an invoice, and then each line with its own request.
An error in the third line left an invoice with two lines in the
database, and a rule over all lines (for example, debits equal credits)
had no moment to run.

The options for the input of the lines:

- **A request for each line, in a transaction of the client.** The API
  has no transactions over many requests, and a client can stop between
  two requests.
- **A batch endpoint for the lines of a record.** The record and its
  lines still come in two requests.
- **The lines in the body of the create and the update of the record.**
  One request writes all, in one transaction. An update must tell the
  lines that stay from the new lines and the lines that go.

## Decision

A `create` or an `update` operation takes the optional key `lines`: the
names of `one_to_many` relations of its entity. The operation writes the
records of these relations with the record, in one transaction.

The FastAPI endpoint takes each relation as a list in the body, for
example `"lines": [{"amount": "12.00"}]`. An item has the fields and the
relations of a new line, without the relation to the record, and an
optional `id`:

- A create adds the record, and then each item as a new line.
- An update with the key replaces the lines: an item with the `id` of a
  line of the record changes the given fields of that line, an item
  without an `id` adds a line, and the lines that no item names go. An
  update without the key keeps the lines.

Each line goes through the repository of its entity (`add`, `change`,
and `remove`, without a commit), so that the checks of the fields, the
rules, the workflows, the validation extension, and the events of the
lines apply. The operation commits once, after all lines. An error in a
line stops the request: nothing stays in the database, and the error
response has the place of the line in `errors`, for example
`["body", "lines", 2]`.

The lines use the permission and the record rules of the operation. The
record rules of the entity of the lines do not apply to them. The lines
of an operation cannot have file fields, because a file comes in its
own request after the record exists.

The front ends send the lines in the same way. An operation with lines
gets a feature slice `src/features/<operation>`, and its function takes
the lines as a second argument, for example
`createInvoice(input, { lines: [...] })`. The slice of the entity of the
lines has the item type and its zod schema, for example
`InvoiceLinesItem` and `invoiceLinesItemSchema`:

- Next.js: the server action checks the items, and writes the record and
  each line through the repositories in one database transaction
  (`inTransaction`). An error in a line rolls back all, and its issues
  have the place of the line, for example `lines.2.amount`.
- React with mock data: the function writes in a transaction of the mock
  stores. An error restores the records of all stores.
- React with the FastAPI app: the function sends the items in the body
  of the request.

A form field of a relation of lines takes `widget: lines`, a lines
editor, and `fields`: the fields and the single relations of the lines,
one column each. The operation of the form must write these lines, and
each required field of the lines needs a column. The editor adds,
changes, and removes rows, and checks each row with the rules of the
lines. Below the rows, the form shows the computed fields of the record
with totals of these lines (ADR 0034), as the record will have them
after the save. An update form reads the lines of the record first,
with the list of the entity of the lines (with the FastAPI app, its
`list` operation).

## Consequences

- A client writes a record and its lines in one request, and a broken
  line leaves no half record.
- A rule over the lines of a record can run after all lines are in the
  transaction.
- An update with the lines sends all lines that stay, also the lines
  that do not change.
- The entity of the lines gets `change` and `remove` in its repository,
  and the record gets one `write_<relation>` function for each relation
  of lines.
- A form edits a record and its lines, and saves them in one request.
  The form shows the totals of the lines before the save.
- A form without a lines editor keeps the lines of an update: its
  function sends no lines.
