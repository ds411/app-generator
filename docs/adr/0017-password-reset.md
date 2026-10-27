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
- The front ends have the public pages `/forgot-password` and
  `/reset-password` (the page of the link), and the sign-in page links
  to the first one.
  - Next.js: server actions with the same token rules (the tag, the
    end time, and the prefix in the signed message). The link starts
    with `PUBLIC_URL`, not with the host of the request, so that a
    caller cannot send a link to another site. In development, without
    `PUBLIC_URL`, the link goes to `localhost`. The delivery is the
    extension file `src/shared/auth/password-reset.ext.ts`, with the
    same stub.
  - React with `x-react-data: api`: the pages call the two endpoints of
    the FastAPI app. `PASSWORD_RESET_URL` is the page `/reset-password`
    of the React app. With mock data, the app has no reset pages: no
    server sends the links.
- The delivery hook is an extension file with a `gap` trace to
  `auth.password_reset` (ADR 0005). Its stub writes the link to the log
  with `ENVIRONMENT=development`, and raises `NotImplementedError`
  (501) in production, so that a production app does not hide a missing
  delivery. (Update for ADR 0023: one hook delivers the messages of all
  kinds, `app/core/messages_ext.py` in the FastAPI app and
  `src/shared/auth/messages.ext.ts` in the Next.js app.)
- Update: `auth.delivery: smtp` replaces the hook with a delivery by
  SMTP, so that an app that sends plain emails needs no code of its own.
  The default stays `extension`. With `smtp`, the FastAPI app has
  `app/core/mail.py` (`smtplib` in a thread, because `smtplib` blocks),
  and the Next.js app has `src/shared/auth/mail.ts` (the package
  `nodemailer`). Both are generated files with `@trace` traces, so the
  trace check reports no gap. The settings `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_TLS`
  (`starttls`, `tls`, or `none`) select the server. Without
  `SMTP_HOST`, the apps keep the behavior of the stub: the log in
  development, and an error in production. The address of an email is
  the email field of the user (`AppDefinition.address_field`), so the
  validator gives an error for `smtp` without one. The room booking
  example uses `smtp`, and `scripts/check-auth-ui.sh` reads the links in
  the emails of the mock SMTP server `scripts/mock_smtp.py`.
- Update (#491): `auth.delivery: ses` sends the messages with
  `SendEmail` of the API v2 of Amazon SES. SES also has an SMTP
  interface, but it needs the SMTP credentials of an IAM user: a secret
  with a long life. The API takes the credentials of the default chain
  of the AWS SDK: the environment variables, EKS Pod Identity or the
  web identity of EKS (IRSA), the role of an ECS task, or the instance
  profile. The settings then have no secret for the email: only
  `AWS_REGION`, `SES_FROM` (a verified sender), and the optional
  `SES_CONFIGURATION_SET`. The FastAPI app has `app/core/mail.py` with
  boto3 in a thread (the client of boto3 blocks), and the dependency
  `boto3` only with `ses`. The Next.js app has `src/shared/auth/mail.ts`
  with the package `@aws-sdk/client-sesv2`. Without `SES_FROM`, the apps
  keep the behavior of the stub. When SES does not send a message, the
  apps answer as for an error of the SMTP server, and the log has the
  error code of SES but not the link. Both SDKs read the endpoint of SES
  from `AWS_ENDPOINT_URL_SESV2`, so the apps have no code for the
  endpoint: `scripts/check-auth-ui.sh` points it to the mock SES server
  `scripts/mock_ses.py`, which checks the header of AWS Signature
  Version 4 and keeps each message.

## Consequences

- The trace check reports the delivery as an open gap until a developer
  writes it, or until the definition selects `delivery: smtp`.
- A delivery by SMTP needs a server and its settings in each
  environment. A mail service with only an HTTP API, other than Amazon
  SES, still needs the hook (`delivery: extension`).
- A delivery with SES needs a verified sender, and the IAM permission
  `ses:SendEmail` for the role of the app. In the sandbox of SES, the
  apps can send only to verified addresses. boto3 is a large
  dependency, so the FastAPI app has it only with `ses` or with the
  files in S3.
- A token stays valid until it ends or the password changes. A second
  request gives a second valid token: both are valid until the password
  changes.
- With the stub in production, a known user name gives 501 and an
  unknown one gives 202. The app must have a delivery before it goes to
  production.
- The reset link of the Next.js app does not work without `PUBLIC_URL`
  in production.
