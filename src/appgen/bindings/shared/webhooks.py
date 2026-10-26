"""A valid sample event of a webhook, for the generated tests and the checks (ADR 0028).

The sample is a body that agrees with the schema of the webhook, with
the event ID `TEST_EVENT_ID` at the property of `event_id` (or 1 for an
integer). A webhook without a schema gets an object with only the event
ID, and a webhook with the event ID in a header gets an empty object.
"""

from typing import cast

from appgen.dsl.openapi import Ref, ScalarSchema, property_chain, resolved, sample
from appgen.dsl.webhooks import Webhook

TEST_EVENT_ID = "evt-1"
"""The event ID of the sample body or of the header."""


def sample_event(webhook: Webhook) -> dict[str, object]:
    """Return a valid sample body of a webhook, with the event ID."""
    spec = webhook.spec
    schema_name = webhook.body_schema
    event_id = webhook.event_id
    body: dict[str, object] = {}
    if schema_name is not None and spec.schemas:
        found = sample(Ref(schema_name), spec)
        body = dict(found) if isinstance(found, dict) else {}
    if event_id.field is not None:
        value: object = TEST_EVENT_ID
        chain = property_chain(Ref(schema_name), event_id.field, spec) if schema_name else None
        if chain:
            last = resolved(chain[-1].schema, spec)
            if isinstance(last, ScalarSchema) and last.type == "integer":
                value = 1
        _set_path(body, event_id.path, value)
    return body


def sample_event_id(webhook: Webhook, body: dict[str, object]) -> str:
    """Return the event ID of a sample body, or `TEST_EVENT_ID` for an ID in a header."""
    if webhook.event_id.header:
        return TEST_EVENT_ID
    return str(event_id_value(webhook, body))


def event_id_value(webhook: Webhook, body: dict[str, object]) -> object:
    """Return the value at the property of the event ID of a body, or None."""
    value: object = body
    for name in webhook.event_id.path:
        value = _member(value, name)
    return value


def _member(value: object, name: str) -> object:
    """Return a property of an object of a sample, or None."""
    return cast(dict[str, object], value).get(name) if isinstance(value, dict) else None


def _set_path(data: dict[str, object], path: tuple[str, ...], value: object) -> None:
    """Set the value at a path of properties, with an object for each missing step."""
    current = data
    for name in path[:-1]:
        step: object = current.get(name)
        if not isinstance(step, dict):
            step = current[name] = dict[str, object]()
        current = cast(dict[str, object], step)
    current[path[-1]] = value


def signature_text(scheme: str, header: str) -> str:
    """Return the check of a signature scheme for the READMEs, in Markdown."""
    match scheme:
        case "stripe":
            return "Stripe (`Stripe-Signature`)"
        case "mailgun":
            return "Mailgun (the fields `timestamp`, `token`, and `signature`)"
        case "basic":
            return "HTTP Basic (`Authorization`)"
        case _:
            return f"HMAC-SHA256 in `{header}`"


def secret_comment(name: str, path: str, scheme: str) -> str:
    """Return the comment of the secret variable of a webhook in `.env.example`."""
    if scheme == "basic":
        return (
            f"The user name and the password of the webhook {name} (POST {path}), as "
            "<user name>:<password>. The URL of the webhook at the mail service has them."
        )
    if scheme == "mailgun":
        return f"The signing key of Mailgun for the webhook {name} (POST {path})."
    return f"The secret of the signatures of the webhook {name} (POST {path})."
