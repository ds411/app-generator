# 0047. The available filter: records without an overlap in a range of days

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

A filter of a view uses the fields of one entity. Real apps find the
holiday homes without a booking on the dates of a guest, the rooms
without a meeting on a day, and the cars without a rental in a week.
The report "appgen Real App Coverage" lists these features for 12
well-known web apps.

The data is already in an app definition: a relation to many records
(the bookings of a listing), and a `no_overlap` rule of their entity,
whose `start` and `end` give the range of a record. The rule also says
how two ranges overlap: the ranges are half-open, so a range that ends
when another starts does not overlap it.

The front ends get their records in two ways. The Next.js app and the
React app with mock data read all records of a view, and filter them in
the browser. The React app with the FastAPI app sends the filters to the
list endpoint. A record rule (ADR 0018, ADR 0025) can hide the bookings
of the other users, and a role can have no list operation of the
bookings, but a listing is not free when another user has a booking.

The options for the days that the user picks:

- **The days of a new related record.** On date fields, the first day
  and the end day, as the ranges of the related records: a check-in and
  a check-out. A guest can arrive on the day that another guest leaves.
- **Whole days.** All days from the first day to the last day. This
  suits date-time fields: the rooms without a meeting on these days.
- **One meaning for both types.** Whole days on date fields keep a
  listing out when another guest arrives on the day that the guest
  leaves. The days of a new record on date-time fields leave out the
  last picked day.

## Decision

A filter of `kind: available` has `rule`: a relation of the entity of
the view to many records (`one_to_many` or `many_to_many`), and a
`no_overlap` rule of the related entity, for example
`bookings.no_double_booking`. It takes `label`, and no `default`. The
validator reports a relation that does not exist or is not to many
records (`unknown-reference`, `unsuitable-field`), and a rule that does
not exist or is not a `no_overlap` rule (`unknown-reference`,
`invalid-option`). Tables, card lists, and maps take the filter.

The filter shows the widget of a date range. It keeps the records
without a related record whose range overlaps the picked days. The
range of a related record is from its start up to its end, as the rule
says. The picked days depend on the type of the fields of the rule:

- On date fields, the days are the range of a new related record: from
  the first day up to the end day. Without an end day after the first
  day, the range is the first day.
- On date-time fields, the days are whole days in UTC: from the start of
  the first day to the end of the last day. Without a last day, the
  range is the first day.

Without a first day, the filter keeps all records. A related record
without a start or an end has no range, as for the rule.

The list endpoint of the FastAPI app takes `<relation>_free_from` and
`<relation>_free_to`, and adds a `NOT EXISTS` subquery
(`~Entity.relation.any(...)`). The React app with the FastAPI app sends
the picked days. The Next.js app and the React app with mock data read
the ranges of the related records once, with the data access of the
entity of the view (`<entity>Ranges`): the ID of the record, the start,
and the end of each related record. The Next.js server action has the
access of the list operation of the entity of the view, and reads all
related records. The mock store reads the records of the related store.
The view keeps the records without a range in the picked days.

## Consequences

- An app finds the free records with the data of its definition: the
  rule that keeps two bookings apart also tells the free listings.
- The filter is correct for all users: a record rule or a role that
  hides the bookings does not make a booked listing free. The ranges
  give only the IDs of the records and the times, not the other values
  of the bookings. A user who may list the records can see when they
  are booked, also from the ranges of the records that a record rule of
  the entity of the view hides.
- The Next.js app and the React app with mock data read all ranges of
  the related records for each view, as they read all records. A large
  table of bookings makes the first load slower.
- The days have two meanings, by the type of the fields of the rule. The
  docs give both, and the generated tests of the FastAPI app check both.
- A filter of the rows of a query, of an API view, or of a dashboard
  widget cannot be an available filter.
