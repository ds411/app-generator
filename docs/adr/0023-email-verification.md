# 0023. Verification of the email address

- Date: 2026-10-25
- Deciders: Maintainers

## Status

Accepted

## Context

With a sign-up (ADR 0016), a person can make an account with the email
address of another person. The apps do not check that a new user owns
the address. The other person cannot sign up later with the address,
and the app sends the messages of the account (for example a reset
link, ADR 0017) to a person who did not ask for them.

The usual check is a message with a link to the address: the account
opens after the user opens the link. The definition does not know the
mail service of the app, so the delivery of the reset link is an
extension file (a generation gap) now. A second extension file for a
second kind of message would give the app developer the same work two
times.

The apps keep the password hashes in the table `credentials`, apart
from the records of the user entity (ADR 0011). An app with users and
data must keep them after a change to the definition: the developer
makes the next migration with `alembic revision --autogenerate`
(ADR 0009).

## Decision

- The key `auth.sign_up.verify_email` turns on the verification. It is
  off by default. `true` gives a link that stays valid for one day. The
  mapping form sets the time: `{ token_minutes: <5 to 10080> }`.
- The address is the user name field if its type is `email`, else the
  first required `email` field of the user entity. The validator
  reports a user entity without one.
- The table `credentials` gets the column `email_verified_at`: the time
  of the verification, or null before it. The column has the server
  default "now", so each credential that the app writes without a value
  is verified: the passwords of an administrator (`app.cli
  set-password`) and of a reset. The migration that Alembic makes for
  an app with data adds the column with the default, so the users that
  exist before the change are verified. Only the sign-up writes a null
  value (`sqlalchemy.null()`, because SQLAlchemy leaves out a plain
  `None` for a column with a server default).
- FastAPI: with `verify_email`, `POST /auth/sign-up` adds the user, its
  credential without a verification, and sends the message with the
  link (`EMAIL_VERIFY_URL?token=...`) in one transaction: a failed
  delivery rolls back the new user, so that the user can sign up
  again. The sign-up gives 202 and no token. A sign-in with the correct
  password of a user who is not verified gives 403. A wrong password
  still gives 401, so the answer tells the state of the account only
  to a caller who knows the password.
- `POST /auth/verify-email/confirm` sets the time with a valid token.
  `POST /auth/verify-email` sends a new link to a user who is not
  verified, and gives 202 with the same answer for each user name.
- A verification token is a signed text of ADR 0020 with its own
  purpose (`email-verification`), the user ID, the end time, and a tag:
  a hash of the address. A token for another address of the user is
  not valid. A second confirmation of a verified user changes nothing,
  so a user can open the link two times.
- A reset link goes to the address too, so a reset also verifies the
  user.
- The sign-in with a provider (ADR 0020) does not ask for the
  verification. When the ID token says that the email address of a
  user is verified (`email_verified: true`, and the claim `email` is the
  address), the app deletes the credential of a user who is not
  verified: nobody proved that the person who chose that password owns
  the address. The user can set a password with a reset link.
- One delivery hook sends all messages of the sign-in. FastAPI:
  `app/core/messages.py` makes a `Message` with the kind
  (`password-reset` or `email-verification`), the user, the address
  (`to`), the subject, the text with the link, and the link. The
  subject and the text are in the language of the request (ADR 0010).
  The extension file `app/core/messages_ext.py` has
  `deliver_message(settings, message)`, with a `gap` trace to each
  element that sends messages, and the stub of ADR 0017: the log with
  `ENVIRONMENT=development`, else 501. It replaces
  `app/core/password_reset_ext.py`.
- The front ends:
  - With the verification, the sign-up form shows a message instead of
    the start page. The public page `/verify-email` is the page of the
    link. It confirms the address only after a click on a button: a
    program that opens the links of a message (for example the scanner
    of a mail service) does not confirm the address.
  - The sign-in of a user who is not verified shows the message of the
    error and the button "Send the link again". The status of the
    sign-in (`signed-in`, `error`, or `unverified`) is the result of
    `signIn` in all apps.
  - Next.js: server actions with the same rules as the FastAPI app (the
    purpose prefix, the tag of the address, the column with the default
    "now", the transaction of the sign-up, and the provider). The link
    starts with `PUBLIC_URL`. `src/shared/auth/messages.ts` makes the
    messages, and the extension file `src/shared/auth/messages.ext.ts`
    (`deliverMessage(message)`) replaces
    `src/shared/auth/password-reset.ext.ts`.
  - React with `x-react-data: api`: the pages call the endpoints of the
    FastAPI app. `EMAIL_VERIFY_URL` is the page `/verify-email` of the
    React app. With mock data, no server sends the links, so the sign-up
    signs in at once, as before.

## Consequences

- A new user needs a delivery of the messages before the first
  sign-in. In production, the stub gives 501 for each sign-up until a
  developer writes the delivery.
- An app of an earlier version keeps its file
  `app/core/password_reset_ext.py` (FastAPI) or
  `src/shared/auth/password-reset.ext.ts` (Next.js), because appgen
  never deletes an extension file. The developer moves the delivery to
  `app/core/messages_ext.py` or `src/shared/auth/messages.ext.ts`, and
  deletes the old file.
- The time of the verification is in the table of the credentials. A
  user without a password (a user of a provider) has no row, and needs
  no verification. A change of the address with the endpoints of the
  user entity does not reset the verification.
- An unverified user who signs in with a provider loses the password of
  the sign-up, and must reset it to sign in with a password again.
- The rate limit of ADR 0013 also applies to the requests for a new
  link. A caller can send a new link to an unverified user many times.
