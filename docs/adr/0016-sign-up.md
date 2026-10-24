# 0016. Sign-up of new users

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

ADR 0011 gives the apps a sign-in with a password, but only an
administrator makes users: `python -m app.cli set-password` in the
FastAPI app, or the seed in the Next.js app. Many apps let a new user
make an account.

A new user must not choose the role, because the role gives the
permissions (ADR 0012). The user entity can have required fields that
the sign-up must fill. A user record without a password, or a password
without a user record, is not useful.

## Decision

- The key `auth.sign_up` turns on the sign-up. It is off by default.
  Its `fields` are the fields of the user entity that the sign-up form
  asks for. With `access`, `default_role` is the role of a new user;
  without it, the default of the role field applies.
- The validator reports a required field without a default that the
  form does not ask for, a required relation of the user entity, the
  role field or a computed field in `fields`, and a role that does not
  exist.
- `auth.min_password_length` (default 8, at least 8) applies to each new
  password: at a sign-up and at each change.
- FastAPI: the public endpoint `POST /auth/sign-up` validates the
  fields and the password, and adds the user record and its
  credential in one transaction. It gives 201 and a bearer token. A user
  name that exists breaks the unique constraint and gives 409.
- The sign-up uses the validation of the entity (the field rules, the
  entity rules, and `validation_ext.py`), because it calls the
  repository of the slice.
- The front ends have the public page `/sign-up`, and the sign-in page
  links to it. The form asks for the fields of `fields`, with the
  default widgets and the zod schema of the user entity, and for a
  password of `min_password_length` or more characters.
  - Next.js: a server action checks the input again, and adds the user
    record and its credential in one transaction of the repository of
    the user entity. Then it sets the session cookie.
  - React with `x-react-data: api`: the page calls `POST /auth/sign-up`,
    and keeps the token as the sign-in does.
  - React with mock data: the page adds the user to the session storage
    of the browser tab, with a SHA-256 hash of the password. This is a
    demonstration, as the mock sign-in is. A reload of the page does not
    delete the user, but the mock records do not show it.

## Consequences

- An app with a sign-up is open to new users. The rate limit of ADR
  0013 also applies to the sign-up.
- The apps do not check that a user owns the email address. A password
  reset (a message to the user) or an external identity provider can
  add a check later.
- The sign-up form has the default widgets of the fields. A form of
  `ui.forms` cannot replace it.
