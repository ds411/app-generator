# 0042. Daily snapshots of the stat widgets

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

A stat widget shows the value of its records now: a count, a sum, an
average, a minimum, or a maximum. A team that tracks a sprint wants a
burndown chart: the open work of each past day. The records do not keep
their old values, so the apps cannot compute the value of a past day
from the records. The change log (ADR 0040) keeps the old values of some
entities, but a replay of the log for each day of a chart is slow, and
the log does not exist for all entities.

The jobs (ADR 0029) run work at the times of a schedule, in the FastAPI
and the Next.js apps, with one run for each time, also with more than
one worker. The React app has no server and no jobs.

The options for the place of the values:

- **A field of a record for each day.** It needs an entity in the
  definition and an operation of a job, which an author writes.
- **A table of the values of the stats.** The apps add it, and a
  built-in job fills it. A row has the dashboard, the widget, the day,
  and the value.

## Decision

A stat widget has the optional key `snapshots: daily`. A chart widget
has the optional key `snapshots`: the name of a stat widget of the same
dashboard with `snapshots: daily`. The chart of snapshots is a line
chart of the stored values of the stat, and `days` (2 to 366, default
30) is the count of days up to today that it shows. It has no `entity`,
`group_by`, `interval`, `aggregate`, `field`, `filter`, `badge`, or
`period_field`. A chart without `snapshots` needs `entity` and
`group_by`.

A snapshot has the value of all records. So the validator reports a
stat with snapshots whose entity has a record rule, because the chart
would show the value of records that a role may not read. A snapshot is
the value of a day, not of the period of the dashboard (ADR 0038), so
the validator also reports a stat with snapshots and `period_field`.

The FastAPI and the Next.js apps keep the table `stat_snapshots`, with
the same columns: the dashboard, the widget, the day (the primary key),
and the value (a double, or null without numbers). The built-in job
`stat_snapshots` runs on the schedule `0 0 * * *` (UTC), with the
machinery of the jobs: the table `job_runs`, the window, the worker of
the FastAPI app, and the route `/api/jobs/stat_snapshots` of the
Next.js app. Each run computes the value of each stat with snapshots at
the time of the run, with the filter of the stat (`$today` is the day
of the run), and stores it as the value of the day of the run. A second
value of the same day replaces the first. The job runs only when the
definition has a stat with snapshots. A job of the definition with the
name `stat_snapshots`, or an entity with the table `stat_snapshots`, is
a generation error.

The FastAPI app computes the value with the query of the stat endpoint:
the dashboard module has a value function, which the endpoint and the
job call. The endpoint of a chart of snapshots
(`GET /dashboards/<dashboard>/<chart>`) gives the stored values of the
days up to `today` (a query parameter, as for the filters with
`$today`), as the groups of a chart: the day as the key. It needs the
permission of the list operation of the entity of the stat.

The Next.js app computes the value with a Drizzle query, with the
filter of the stat in the database, as the jobs do. The field of the
aggregate must be a stored field of the entity of the stat, else the
generation fails. A server action for each chart of snapshots gives the
stored values, with the permission of the list operation of the entity
of the stat.

The React app shows the stored values of the FastAPI app with
`x-react-data: api`. With the mock data, there are no stored values:
the chart shows the value of today, from the records in the browser.

## Consequences

- A burndown chart needs one key on the stat and one chart widget. The
  author writes no job and no entity.
- The chart starts empty: the first value comes at the first run of the
  job after the deployment. The values of the days before stay unknown.
- A day without a run (the worker or the scheduler stopped for longer
  than the window) has no value, and the line of the chart skips it.
- The value of a day is the value at 00:00 UTC, not at the end of the
  day in the time zone of the users.
- The table grows by one row for each stat each day. The apps do not
  delete old rows.
- A rename of a dashboard or of a stat widget starts a new series, and
  the rows of the old name stay in the table.
