# 0017. Password reset

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

A user who forgets the password needs an administrator to set a new one
(ADR 0011). Usually an app sends a message with a one-time link, for
example by email. The definition does not know the mail service of the
app, and a test cannot send real messages.

A reset link must be valid for a short time and only one time. It must
not tell a caller which user names exist. ADR 0011 keeps the sign-in
without new packages and with no table except `credentials`.

## Decision

- The key `auth.password_reset` turns on the reset. It is off by
  default. `token_minutes` (default 60) is the time that a link stays
  valid.
- A reset token is a signed text (HMAC-SHA256 with `AUTH_SECRET`) with
  the user ID, the end time, and a tag: a hash of the current password
  hash. A new password changes the tag, so the reset itself, and each
  other change of the password, make the earlier tokens invalid. The
  apps need no new table and no new package. The signed message has a
  prefix, so that a session token is never valid as a reset token, and
  the reverse.
- FastAPI: `POST /auth/password-reset` makes the token and calls the
  delivery hook with the link (`PASSWORD_RESET_URL?token=...`). It gives
  202 with the same answer for an unknown user name. `POST
  /auth/password-reset/confirm` sets the new password with a valid
  token, and gives 400 for a used, an ended, or a changed token.
- The delivery hook is an extension file with a `gap` trace to
  `auth.password_reset` (ADR 0005). Its stub writes the link to the log
  with `ENVIRONMENT=development`, and raises `NotImplementedError`
  (501) in production, so that a production app does not hide a missing
  delivery.

## Consequences

- The trace check reports the delivery as an open gap until a developer
  writes it.
- A token stays valid until it ends or the password changes. A second
  request gives a second valid token: both are valid until the password
  changes.
- With the stub in production, a known user name gives 501 and an
  unknown one gives 202. The app must have a delivery before it goes to
  production.
- The front ends add the pages in a separate story. The Next.js app
  uses the same token rules.
