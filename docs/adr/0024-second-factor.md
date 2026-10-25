# 0024. Second factor of the sign-in

- Date: 2026-10-25
- Deciders: Maintainers

## Status

Accepted

## Context

A user signs in with a user name and a password (ADR 0011). A person
who gets the password of another person, for example from a leak of
another site, can sign in as that person. A second factor stops this
attack: the sign-in also needs a thing that only the user has.

The usual second factor of web apps is a time-based one-time password
(TOTP, RFC 6238): an authenticator app on the phone of the user makes a
new code of 6 digits each 30 seconds from a shared secret. The app and
the authenticator app need no network between them, and no message
service (ADR 0017 and ADR 0023 have no delivery in production until a
developer writes it).

The apps must not need a new package for the codes: HMAC-SHA-1 is in the
standard library of Python and in `node:crypto`.

## Decision

- The key `auth.second_factor` with `totp: true` lets each user with a
  password turn on a second factor. It is off by default. With `access`,
  `required_roles` names the roles that must use it. `totp` is the only
  method now: a later method gets its own key, and the validator needs
  one method.
- The codes follow RFC 6238 with the values of the usual authenticator
  apps: HMAC-SHA-1, 6 digits, and steps of 30 seconds. The app accepts
  the codes of one step before and one step after the current step, for
  the difference of the clocks. The app keeps the last step that a user
  signed in with, and accepts only later steps: each code is valid one
  time.
- A user turns the factor on in two steps. The setup gives a new random
  secret of 20 bytes, as base32 text and as an `otpauth://` URI for a QR
  code. The confirmation with a valid code turns the factor on, and
  gives 10 recovery codes one time. A recovery code has 16 random base32
  characters (80 bits). The app keeps only the SHA-256 hash of each
  recovery code, and deletes the hash when the user signs in with it.
  The high entropy of the codes makes a slow hash unnecessary.
- The table `credentials` keeps the second factor: the encrypted secret,
  the time that the user turned it on, the last step, the number of
  wrong codes in a row, the end of a lock, and the hashes of the
  recovery codes. All columns are nullable or have a server default, so
  the migration that Alembic makes adds them to an app with data, and
  the users that exist have the factor off.
- The app keeps the secret encrypted with a key from `AUTH_SECRET`, so
  that a copy of the database alone (for example a backup) does not give
  the secrets. The standard library has no AES, so the encryption uses
  HMAC-SHA-256: two keys come from `AUTH_SECRET` (one encrypts, one
  checks). The key stream is the HMAC of a random nonce of 16 bytes, and
  the tag is the HMAC of the nonce and the encrypted secret. A changed
  value, or another `AUTH_SECRET`, gives no secret.
- A sign-in with the correct password of a user with the factor gives a
  challenge, not a token: a signed text of ADR 0020 with its own purpose
  (`second-factor`), the user ID, and an end time of 5 minutes. `POST
  /auth/sign-in/second-factor` with the challenge and a code, or a
  recovery code, gives the token.
- A user of a required role without the factor gets a challenge of the
  kind `setup`. The setup and the confirmation accept the challenge
  instead of a token, and the confirmation gives the token. So the user
  turns the factor on before the first token. The role of the sign-up
  can be a required role only with `verify_email` (ADR 0023): without
  it, the sign-up gives a token at once. The validator reports this
  case.
- After 5 wrong codes in a row, the app refuses the codes of the user
  for 15 minutes (429). The rate limit of ADR 0013 also applies to the
  code step. Without the lock, a caller with the password could try many
  codes from many addresses.
- The signed-in user turns the factor off with a code or a recovery
  code. A user of a required role cannot turn it off. The command
  `python -m app.cli disable-second-factor <user name>` turns it off for
  a user who lost the authenticator app and the recovery codes.
- The sign-in with a provider (ADR 0020) does not ask for the second
  factor: the provider has its own sign-in, and can have its own second
  factor.
- FastAPI: `app/core/second_factor.py` has the codes, the encryption,
  and the endpoints. `app/core/auth.py` gives the challenge.
- The front ends have the page `/second-factor` of the signed-in user
  and a link to it in the top bar. The page turns the factor on with the
  QR code and the key, shows the recovery codes one time, and turns the
  factor off. After the password of a user with the factor, the sign-in
  page asks for a code or a recovery code, and a user of a required role
  turns the factor on first. The browser makes the QR code, so the
  secret goes to no service on the network.
- Next.js: `src/shared/auth/second-factor.ts` has the codes and the
  encryption with `node:crypto`, and server actions in
  `src/shared/auth/second-factor-actions.ts` follow the rules of the
  FastAPI app. The React app with `x-react-data: api` calls the
  endpoints of the FastAPI app. The React app with mock data has the
  factor as a demonstration in the browser tab, as its mock sign-in.

## Consequences

- A change of `AUTH_SECRET` makes the secrets of all users unreadable,
  as it makes the tokens invalid. The users with the factor sign in with
  a recovery code, and turn the factor off and on again. An
  administrator can turn it off with the command.
- A user who loses the authenticator app and the recovery codes needs
  an administrator.
- A person who has the password of a user of a required role who never
  signed in can turn the factor on first. The administrator gives the
  first password, so the risk is small.
- An attacker with the password can lock the codes of a user for 15
  minutes. The user must then change the password, because the attacker
  has it.
- The front ends have the package `uqr` for the QR code. The package is
  small and has no dependencies. A QR code service on the network would
  get the secret.
