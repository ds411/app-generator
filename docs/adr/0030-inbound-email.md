# 0030. Inbound email in webhooks

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

An app such as a help desk makes a ticket of each email to its support
address, and adds each reply to the ticket. An app cannot receive email
itself: a mail service receives it, and forwards each email as an HTTP
request to a URL of the app. The webhooks of ADR 0028 receive signed
JSON events, but the mail services send other requests:

- Mailgun forwards an email from a route with the action `forward`. The
  body is a form (URL-encoded, or multipart with the attachments). The
  fields have the parsed email, and the field `message-headers` has all
  headers as a JSON list. The fields `timestamp`, `token`, and
  `signature` have the HMAC-SHA256 of the time and the token with the
  signing key.
- Postmark posts JSON with the parsed email (`FromFull`, `ToFull`,
  `Subject`, `TextBody`, `Headers`, `Attachments`). It does not sign the
  request. It sends HTTP Basic credentials when the URL of the webhook
  has them.
- SendGrid posts a multipart form from its Inbound Parse webhook, with
  the parsed fields and the header lines of the email. Its signed
  requests use an ECDSA key, and the headers of a security policy. It
  also sends HTTP Basic credentials from the URL, as Postmark does.
- A mail service delivers an email again when the app gives an error,
  as the other senders do. The `Message-ID` header names an email, and
  the `In-Reply-To` header of a reply names the email that it answers.
- The files of an email can be large, and the apps have no storage for
  the files of a webhook yet.

## Decision

- A webhook takes the key `format`: `json` (the default) or `email`.
  A webhook with `format: email` takes the key `provider`: `mailgun`,
  `postmark`, or `sendgrid`. It has no `body` and no `event_id`.
- Two new signature schemes: `mailgun` (the fields of the form, with
  `tolerance_seconds` for the time, as `stripe`), and `basic` (HTTP
  Basic authentication, with the secret `<user name>:<password>`). The
  validator accepts only the schemes of the provider: `mailgun` or
  `basic` for Mailgun, and `basic` for Postmark and SendGrid. `basic`
  suits a JSON webhook too. We do not support the ECDSA signatures of
  SendGrid in this version.
- The apps read the request of each provider into one `InboundEmail`:
  the `Message-ID`, the sender of the `From` header, the receivers of
  `To` and `Cc`, the subject, the text, the HTML, the `In-Reply-To`
  header, and the name, the type, and the size of each attachment. The
  apps do not keep the content of the attachments.
- The event ID of an email is its `Message-ID` header, or the SHA-256
  hash of the body for an email without one. The table `webhook_events`
  and the rules of the repeated events of ADR 0028 do not change.
- The FastAPI app has the module `app/core/inbound_email.py` with the
  Pydantic models and a reader for each provider of the app. The
  Next.js app has `src/shared/webhooks/email.ts` with the types,
  the readers, and `receiveEmail`, which shares the delivery of the
  event with `receiveWebhook`. The gap function of each webhook gets
  the email.
- The fixture `tests/fixtures/inbound-email.yaml` has a webhook for each
  provider, with hand-written logic that makes a ticket of an email and
  counts the replies. `scripts/inbound_email_test.py` sends emails in
  the format of each provider to the FastAPI and the Next.js apps.

## Consequences

- An app author declares an email webhook in a few lines, and writes
  only the logic of the email, for example a ticket and its replies.
- The apps parse only the parsed formats of the providers, not the raw
  MIME message. The texts are as the provider gives them: an encoded
  header (RFC 2047) of SendGrid can stay encoded.
- HTTP Basic credentials in a URL are safe only with HTTPS, and the mail
  service keeps them in its settings. An app that needs the signed
  requests of SendGrid needs a later scheme.
- An email without a `Message-ID` gets the hash of the body. A provider
  that changes the body on a second delivery, for example Mailgun with
  a new token, then runs the logic two times.
- The logic gets only the names and sizes of the attachments. An app
  that keeps the files needs the file fields of ADR 0027 and the content
  of the attachments, in a later version.
