# 0044. Emails of the notices

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

The notices (ADR 0041) show in the bell of the app. A user that does
not open the app does not see them. Many apps also send the important
notices by email, and let each user turn off the emails that the user
does not want.

The FastAPI and the Next.js apps can send emails: the delivery of the
messages of the sign-in by SMTP (`auth.delivery: smtp`, ADR 0017) sends
each message with the SMTP server of the settings `SMTP_*` to the
email address of the user (ADR 0023).

A notice comes in the transaction of a change. An email cannot go back
when the transaction rolls back, so the email must go after the commit.
The options:

- **Send the emails in the request, after the commit.** The emails go at
  once. But the request waits for the SMTP server, an error of the SMTP
  server loses the email, and a change in a job or in an event (ADR 0031)
  has no single point after its commit.
- **Mark the notices that wait for an email, and send them in a job.**
  The table of the notices is the queue (an outbox). The jobs (ADR 0029)
  already run work at a later time, one time with any number of workers,
  in the FastAPI and the Next.js apps. The emails go a little later, and
  a failed email goes again at the next run.

## Decision

A notification takes `email: true`. It needs `auth.delivery: smtp`
(`invalid-option`), so the user entity has the field of the email
address. The receivers of a notification with `email: true` get each
notice of it in the bell and by email.

- The notice gets the column `email`: true while its email waits. The
  repositories set it in the transaction of the change, for the
  notifications with `email: true`.
- The built-in job `notice_emails` runs each minute (`* * * * *`, UTC),
  with the machinery of the jobs: the table `job_runs`, the worker of the
  FastAPI app, and the route `/api/jobs/notice_emails` of the Next.js
  app. A run takes the oldest 100 notices that wait. For each one, it
  sends the email, unless the user turned off the emails of the
  notification, and then sets `email` to false. At the first error of the
  SMTP server, the run stops, and the rest waits for the next run. A job
  of the definition with the name `notice_emails` is a generation error.
- The email goes to the email address of the user, from `SMTP_FROM`.
  The subject is the title of the app and the text of the notice. The
  text has the text of the notice, the link to the detail page of the
  record (if the entity has one), and the link to the page of the
  settings. The app does not store the language of a user, so the email
  has the default language of the app.
- The table `notice_settings` keeps the choices of the users: the user,
  the name of the notification, and `email`. Without a row, the emails
  are on. The rows of a deleted user go with the user.
- The FastAPI app gives the settings of the signed-in user with
  `GET /notices/settings`: each notification with `email: true` and its
  state. `PUT /notices/settings/{notification}` with `{"email": false}`
  turns off the emails of one notification. The setting `FRONT_END_URL`
  gives the start of the links in the emails. The Next.js app has server
  actions for the same, and the links start with `PUBLIC_URL`.
- The front ends have the page `/notice-settings`: a switch for each
  notification with `email: true`, with the name of the notification in
  words. A change saves at once. The bell has a link to the page. The
  React app with mock data keeps the choices in the session storage, and
  sends no emails.
- As for the messages of the sign-in, without `SMTP_HOST` the
  development app writes each email to the log. The production app
  writes an error to the log, and the emails wait.

The mentions (ADR 0043) give no emails.

## Consequences

- An author turns on the emails of a notification with one key, and
  writes no job and no template.
- An email goes up to a minute or two after the change: the scheduler
  calls the job each minute. An app without a running scheduler (the
  worker of the FastAPI app, or a CronJob of the route of the Next.js
  app) sends no emails, and the notices wait.
- An email can go two times: when the SMTP server takes it and the run
  then fails before its commit.
- A user turns off the emails of one notification, but not the notices
  in the bell, and not the emails of all notifications at once.
- The emails have no HTML part, and one email goes for each notice: the
  apps do not collect the notices of a user into one email.
- A notice of a notification that loses `email: true` gets no email,
  also when it waits. A notice from before a notification gets
  `email: true` gets no email.
