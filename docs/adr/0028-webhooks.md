# 0028. Signed webhooks

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

Other systems send events to an app over HTTP: a payment service
reports a payment, a shipping service reports a delivery, and a chat
service sends a message to a bot. Each sender calls a URL of the app
with a JSON body, and signs the request with a secret that the sender
and the app share. Before this decision, each endpoint of the generated
apps was an operation on a record of the app. Such an event has no
record, and needs its own checks.

The constraints:

- The signature is over the raw bytes of the body. A check after the
  JSON parser cannot work, because the parser changes the spaces and the
  order of the keys.
- The common senders use two kinds of signatures. Most use an
  HMAC-SHA256 of the body in a header, in hex or in base64, with an
  optional prefix (for example GitHub, Shopify, and many chat services).
  Stripe signs `<time>.<body>`, and puts the time and the signature in
  the header `Stripe-Signature`, so that an app can reject an old
  request.
- A sender delivers an event again when it gets no answer, or an error.
  A repeated delivery must not run the logic of the app two times.
- The logic of an event is specific to the app (ADR 0005).
- The same definition must give the same output, without a network
  (ADR 0004). The schema of a body is often in an OpenAPI document of
  the sender (ADR 0019).

## Decision

### The `webhooks` section

- A new optional top-level section `webhooks` maps a webhook name to a
  webhook element with the ID `webhooks.<name>`. A webhook has a `path`,
  a `signature`, an `event_id`, an optional `body`, and an optional
  `description`.
- The signature has a `scheme` and `secret_env`, the environment
  variable of the secret. The scheme `hmac_sha256` needs a `header`,
  and has an optional `prefix` and `encoding` (`hex` or `base64`). The
  scheme `stripe` has the fixed header `Stripe-Signature`, and an
  optional `tolerance_seconds` (the default is 300, as in the Stripe
  libraries). A key of the other scheme is an error (`invalid-option`).
- `event_id` gives the location of the ID of the event: `field`, a path
  of properties of the body (for example `data.id`), or `header`. The
  default is the property `id`.
- `body` names a schema of an OpenAPI document: `document` and
  `schema`. The loader reads the document as for `apis`, and the output
  manifest records its hash. Only the schema and the schemas that it
  refers to go into the app. Without `body`, the event is a JSON value.

### The checks of the validator

- A path cannot be the path of another webhook, a path of a page (a
  parameter of the page matches each segment), or a path under the
  endpoints of an entity in the FastAPI app (`duplicate-path`). A path
  under a route of the apps, for example `/auth`, `/apis`, `/docs`, or
  `/health`, is reserved (`reserved-name`).
- The secret variable cannot be a variable of the apps, of an API, or
  of another webhook, and cannot have a public prefix of the front-end
  builds (`NEXT_PUBLIC_`, `VITE_`).
- The schema must be in the document (`unknown-reference`, with a hint
  for a close name), and the property of the event ID must be in the
  schema.

### The FastAPI app

- Each webhook has a package `app/webhooks/<webhook>/`: the endpoint
  `POST <path>` (`router.py`), the Pydantic models of the schema
  (`models.py`), and the extension file `handler_ext.py` with the gap
  function `handle_<webhook>`. The function gets the database session,
  the typed event, and the headers.
- The endpoint reads the raw body, and checks the signature with
  `hmac.compare_digest`. A wrong or missing signature gives 401, and a
  Stripe time outside the tolerance gives 401 too. A server without the
  secret gives 500, so that a missing setting does not accept each
  request. A body that is not JSON, or an event without an ID, gives
  400, and a body that does not agree with the schema gives 422.
- The table `webhook_events` keeps the name of the webhook and the event
  ID, with a unique constraint on the two. The endpoint adds the row and
  then calls the logic, in the same transaction. A repeated event gives
  200 with `"repeated": true`, and the logic does not run. When the logic
  fails, the transaction does not keep the row, so the sender can
  deliver the event again. When two deliveries come at the same time,
  the unique constraint stops the second one. An ID that is longer than
  the column is stored as its SHA-256 hash.
- The generated tests sign the requests with a test secret, and replace
  the logic with a function that records the events. They check one run
  for each event ID, 401 for a wrong, changed, or missing signature, 400
  for an event without an ID, and 500 without a secret.
- The secrets go into the settings, `.env.example`, and the files of
  the deployment, as the other secrets do.

### The other apps

- The React app has no server, so it leaves out the kind `webhook` by
  design.
- The Next.js app has a route handler `app/<path>/route.ts` for each
  webhook, and a feature slice `src/features/<webhook>-webhook/`: the
  function that receives the request (`api/<webhook>-webhook.gen.ts`),
  the extension file with the gap function `handle<Webhook>`
  (`api/<webhook>-webhook.ext.ts`), and the TypeScript types and zod
  schemas of the schema (`model/event.ts`). The suffix `-webhook` keeps
  the slice apart from the slice of an operation with the same name.
- `src/shared/webhooks/` checks the signatures with `timingSafeEqual`,
  and gives the same statuses and answers as the FastAPI app. The
  Drizzle table `webhook_events` has the same columns and the same
  unique constraint.
- PGlite cannot nest a transaction, and the repositories of the app
  open their own transactions. So the endpoint adds the row of the event
  with `onConflictDoNothing` before it calls the logic, and deletes the
  row when the logic fails. A failed logic thus keeps the changes that
  it made before the error. A `WebhookError(status, message)` of the
  logic gives its status to the sender.

## Consequences

- An app author declares a webhook in a few lines, and writes only the
  logic of the event. The checks of the signature and of a repeated
  delivery are the same in each app.
- The two schemes cover most senders. A sender with another kind of
  signature (for example a signature over the URL and the parameters,
  or an asymmetric key) needs a later scheme.
- The table `webhook_events` grows with each event. The app does not
  delete old rows. An app with many events must delete them by hand
  code or by a job.
- The logic runs in the request. Long logic can pass the timeout of the
  sender, which then delivers the event again. The row of the event
  stops the second run only after the first run commits.
