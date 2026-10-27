# 0033. Calls of an API in the name of a user

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

An app can sync the mailbox, the calendar, or the bank account of a
user. The service of the account has an API with OAuth 2.0, and the app
calls it with an access token of the user. The clients of the APIs
([ADR 0019](0019-third-party-apis.md)) had the client credentials flow:
one token of the app for all requests.

- The authorization code flow (RFC 6749, section 4.1) gives a token of a
  user. The browser goes to the authorization URL of the service, the
  user allows the access, and the service sends the browser back to the
  app with a code. The app changes the code for an access token and a
  refresh token at the token URL, with the client ID and the client
  secret. PKCE (RFC 7636) makes a stolen code useless.
- An access token ends after a short time. The refresh token gives a
  new access token without the user. A service can give a new refresh
  token at each refresh, and then the old one stops working.
- A token of a user is a secret of the user. A copy of the database
  must not give the tokens.
- The front ends call the FastAPI app with a bearer token
  ([ADR 0011](0011-auth.md)), not with cookies. A browser that goes to
  another site sends no bearer token, so the start of the flow cannot be
  a link to the app.
- A job runs without a signed-in user ([ADR 0029](0029-jobs.md)).
- The sign-in with a provider ([ADR 0020](0020-providers.md)) is also an
  authorization code flow, but its result is a session of the app, not
  a token for an API.
- Some APIs take HTTP Basic with the credentials of a person, not
  OAuth 2.0 (#487). Jira Cloud takes the email address of an Atlassian
  account and an API token of this account. An issue that the app makes
  with the token of an agent has this agent as the reporter.

## Decision

- `apis.<api>.security` takes `flow: authorizationCode`: the scheme of
  the document must have this flow. Without `flow`, the client
  credentials flow is the default if the scheme has it. The app needs
  `auth`, and no public operation can call the API.
- The FastAPI app has the routes of the flow in
  `app/core/connections.py`, under `/auth/connections`:
  - `GET /auth/connections` lists the APIs with the flow, and the
    connections of the signed-in user.
  - `POST /auth/connections/<api>` gives the authorization URL for the
    signed-in user. The front end sends the browser to it.
  - `GET /auth/connections/<api>/callback` is public. It changes the
    code for the tokens, and sends the browser back to `return_to` (a
    page of a front end in `CORS_ORIGINS`) with `#connected=<api>` or
    `#error=...`. Without `return_to`, it returns the connection as JSON.
  - `DELETE /auth/connections/<api>` deletes the connection.
- The `state` of the flow is signed with `AUTH_SECRET`. It holds the
  user, a nonce, `return_to`, and the end of its time (10 minutes). The
  PKCE verifier is an HMAC of the nonce, so the app needs no cookie, and
  no URL has the verifier.
- The table `api_connections` keeps the tokens of each user and API,
  encrypted with AES-256-GCM. The key is an HMAC of `AUTH_SECRET`. The
  API, the user, and the column are the associated data of each value,
  so a value is valid only in its own row and column. The dependency is
  `cryptography`.
- A client gets a token source (`UserToken`), the same interface as the
  source of the client credentials flow. The source reads the access
  token of the user, and gets a new one with the refresh token a little
  before the token ends, or after an answer with the status 401. A lock
  for each user and API in the process, and a row lock in Postgres, make
  two requests at the same time wait for the same new token. If the
  token endpoint does not accept the refresh token, the source deletes
  the connection.
- A custom operation that calls the API gets the client of the
  signed-in user. Without a connection, the endpoint gives 409. A job
  names the user of each record in `user`. A run for a record whose user
  has no connection does nothing.
- The Next.js app has the same table, the same encryption, and the same
  token source in `src/shared/auth/connections.ts`. The browser of the
  signed-in user goes to `/connections/<api>/start`, which sends it to
  the authorization URL. The state, the PKCE verifier, the user, and the
  end of the time of the flow are in an HTTP-only cookie for the path
  `/connections/<api>`, signed with `AUTH_SECRET`. The Next.js app has
  the session cookie, so the start can be a link.
  `/connections/<api>/callback` changes the code for the tokens, and
  sends the browser to `/connections` with `#connected=<api>` or
  `#error=...`. A server action that calls the API without a connection
  gives an error result with a message. A job runs the operation for
  each record in the name of its user (`asUser`).
- The front ends have the page `/connections` for the signed-in users,
  and a link to it in the layout. The page lists the APIs with the flow,
  and connects or disconnects each account. It shows the result of the
  callback from the fragment of the URL, and removes the fragment. The
  React app with `x-react-data: api` uses the routes of the FastAPI app,
  with `return_to` set to its page. The React app with mock data keeps
  the connections in `sessionStorage`, and sends no requests. A page of
  the definition cannot have the path `/connections`, or a path under
  `/connections/`, when an API has the flow.

### HTTP Basic with the credentials of each user (#487)

- `apis.<api>.security` takes `per_user: true` with an HTTP Basic
  scheme, and then no `username_env` and no `env`. The optional `check`
  names an operation of the API without required values. The rules of
  `auth`, the public operations, and the jobs are the same as for the
  flow.
- The same table keeps the credentials: the user name in the new column
  `username`, and the password in the column of the access token, with
  the same encryption and associated data. The new column `rejected_at`
  marks credentials that the API did not accept. The table has the
  columns only when an API has `per_user`.
- `POST /auth/connections/<api>` takes `username` and `password` for
  such an API. With `check`, the server calls the operation with the
  credentials first, and keeps them only after a success: an answer with
  the status 401 or 403 gives 422, and another failure gives 502. The
  list of the connections gives the kind (`oauth` or `basic`), the user
  name, and `rejected`, never the password.
- The token source `UserCredentials` gives the Base64 of
  `<user name>:<password>`, and the client sends `Basic` in place of
  `Bearer`. After an answer with the status 401, the source marks the
  connection as rejected and raises the error of a missing connection
  (409). The source does not delete the connection: the page shows the
  user name and asks for new credentials. New credentials clear the
  mark.
- The Next.js app has the same column, the same source, and the server
  action `connectWithCredentialsAction`. It has no routes of the flow
  for these APIs.
- The page `/connections` shows a form with the user name and the
  password (`autocomplete="off"` for the password, as it is a token of
  another service) for each such API. An app with both kinds of APIs
  shows both kinds of items. The React app with mock data keeps only the
  user name in `sessionStorage`.
- An app with only such APIs needs no `PUBLIC_URL`.

## Consequences

- An app can call an API in the name of each user, also in a job.
- The tokens of the users are useless without `AUTH_SECRET`. A new
  `AUTH_SECRET` ends the sessions and the connections: the users connect
  their accounts again.
- The source keeps the new tokens in a session of its own (in the
  Next.js app, outside the transaction of the job), so a failed
  operation does not lose a new refresh token. With SQLite (local runs),
  a run of a job holds the lock of the database: a refresh of a token in
  the run waits for the lock, and fails after the timeout of SQLite. The
  worker in production uses Postgres.
- The callback of the FastAPI app trusts the user in the signed
  `state`, not a cookie. A person who gets the authorization URL of
  another user in the 10 minutes can connect an account of their own to
  that user. The URL goes only to the browser of the user. The callback
  of the Next.js app also compares the user of the flow cookie with the
  signed-in user.
- The OAuth app of the service must allow the URL of the callback. The
  Next.js app builds it from `PUBLIC_URL` (in production, the variable
  is necessary). The FastAPI app uses `PUBLIC_URL`, else the URL of the
  request.
- The app does not revoke the tokens at the service when a user
  deletes a connection: OpenAPI has no field for the revocation URL.
- With `per_user`, the server keeps a password of another service. The
  encryption and the associated data are the same as for the tokens, and
  no answer contains the password. The user can revoke the API token at
  the service at any time.
- Without `check`, the app keeps credentials that can be wrong. The
  first call with them marks the connection as rejected.
