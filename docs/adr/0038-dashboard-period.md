# 0038. The period of a dashboard

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

Before this decision, the filter of a dashboard widget was fixed. Only
`$today` and `$now` changed with the day. A user could not see the
values of the last 7 days, and then of the last month, on the same
dashboard. Analytics and sales apps have a picker of a date range above
their widgets, and a stat that shows the change from the period before.

- The dashboards of the Next.js app and of the React app without an API
  read all records of their entities and compute the widgets in the
  browser (ADR 0003). The React app with `x-react-data: api` calls one
  endpoint of the FastAPI app for each widget, and the database computes
  the value (M26).
- The day of today depends on the time zone of the user. The browser
  knows it, and the server does not. The filters already send `today`
  from the browser for `$today`.
- A widget can show records of more than one date field, or records
  without a date. Not all widgets of a dashboard show the same dates.
- "The period before" has more than one meaning: the calendar unit
  before (last month for this month), or the days of the same length
  just before the range.

## Decision

We give a dashboard an optional `period`: a `default` range and the
`ranges` that the picker offers. The ranges are names, for example
`last_30_days`, `this_month`, `last_month`, `all`, and `custom` (the
user picks the days). The browser computes the first and the last day
of a range from the day of today of the user. A `this_*` range ends
today. A week starts on the first day of the week of the locale of the
selected language, else on Monday.

We give a stat, a chart, and a list widget an optional `period_field`,
a date or a date-time field of its entity. The widget shows the records
whose value of that field is in the days of the range, and a date and
time is in the range of its day in UTC, as in the filters. A widget
without `period_field` shows all records. The validator requires a
`period_field` for a period, and a period for a `period_field`.

We give a stat widget `compare: previous`. The previous period has the
same number of days, and ends on the day before the first day of the
range. The tile shows the change as a percentage with its sign. A range
without a first or a last day has no previous period, and no change.

In the browser, the dashboard filters the records of each widget by the
period. With the API client, the endpoint of a widget with a period
field takes `start` and `end` (dates), and the dashboard sends the
days of the range. For a compare, the dashboard calls the same endpoint
again with the days of the previous period. A new range loads the
values again, and the dashboard shows the last values until then.

## Consequences

- An app author gets a date range picker and the change from the
  previous period with two keys, and the three bindings give the same
  values for the same records.
- The period is not in the URL: a reload, or a link to the page, shows
  the default range.
- A compare with the API client makes two requests for each stat. The
  endpoints stay simple: each endpoint gives the value of one range.
- The previous period of `this_month` is the same number of days before
  the first day of the month, not the whole last month. The docs say
  this, and an app author can pick `last_month` for a whole month.
- A widget reads one date field for the period. A widget that needs two
  date fields, for example a start and an end, is a custom widget.
