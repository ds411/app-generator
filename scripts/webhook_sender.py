"""Sign and send webhooks to a generated app, as the sender of a webhook does (ADR 0028).

`sign` gives the headers of a signed request for a webhook of a
definition: an HMAC-SHA256 of the body in a header (`hmac_sha256`), or
the header `Stripe-Signature` with a time (`stripe`). `secrets` gives a
test secret for each webhook, as environment variables for the app.

The smoke test (`scripts/smoke_test.py`) starts the project tracker with
these secrets, and calls `check_commits`: it sends the event of the
webhook `commits` two times with a correct signature and one time with a
wrong signature, and checks that the hand-written logic of the example
adds one comment to the task.
"""

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from appgen.dsl import AppDefinition
from appgen.dsl.webhooks import Webhook


class WebhookError(Exception):
    """A check of a webhook failed."""


@dataclass(frozen=True, slots=True)
class Answer:
    status: int
    body: str


def secrets(definition: AppDefinition) -> dict[str, str]:
    """Return a test secret for each webhook, by the environment variable of the secret."""
    return {
        webhook.signature.secret_env: f"test-secret-{name}"
        for name, webhook in definition.webhooks.items()
    }


def sign(webhook: Webhook, body: bytes, secret: str, at: int | None = None) -> dict[str, str]:
    """Return the headers of a request with the signature of the scheme of the webhook."""
    signature = webhook.signature
    headers = {"Content-Type": "application/json"}
    if signature.scheme == "stripe":
        timestamp = int(time.time()) if at is None else at
        signed = f"{timestamp}.".encode() + body
        digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        headers["Stripe-Signature"] = f"t={timestamp},v1={digest}"
        return headers
    raw = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    text = base64.b64encode(raw).decode() if signature.encoding == "base64" else raw.hex()
    headers[signature.signature_header] = signature.prefix + text
    return headers


def send(url: str, body: bytes, headers: dict[str, str]) -> Answer:
    """Send a POST request, and return the status and the body of the answer."""
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return Answer(response.status, response.read().decode())
    except urllib.error.HTTPError as error:
        return Answer(error.code, error.read().decode(errors="replace"))


def check_commits(
    definition: AppDefinition,
    base: str,
    task_id: str,
    author_email: str,
    comments: Callable[[], int],
    log: Callable[[str], None],
) -> None:
    """Send the event of the webhook `commits` of the project tracker, and check the comments.

    `comments` gives the number of comments of the task. A correct
    signature adds one comment, also when the event comes again, and a
    wrong signature gives 401 and no comment.
    """
    webhook = definition.webhooks["commits"]
    secret = secrets(definition)[webhook.signature.secret_env]
    event = {
        "id": f"evt-{task_id}",
        "task_id": task_id,
        "author_email": author_email,
        "message": "Fix the build (refs the task)",
        "url": "https://code.example.com/commits/1",
    }
    body = json.dumps(event).encode()
    url = base + webhook.path
    before = comments()
    wrong = send(url, body, sign(webhook, body, "a-wrong-secret"))
    if wrong.status != 401:
        raise WebhookError(f"POST {webhook.path} with a wrong signature gave {wrong.status}.")
    if comments() != before:
        raise WebhookError(f"POST {webhook.path} with a wrong signature added a comment.")
    log(f"POST {webhook.path} with a wrong signature gives 401")
    for repeated in (False, True):
        answer = send(url, body, sign(webhook, body, secret))
        if answer.status != 200:
            raise WebhookError(f"POST {webhook.path} gave {answer.status}: {answer.body}")
        receipt = json.loads(answer.body)
        if receipt.get("repeated") is not repeated:
            raise WebhookError(f"POST {webhook.path} gave {receipt}, not repeated={repeated}.")
    added = comments() - before
    if added != 1:
        raise WebhookError(f"Two deliveries of one event added {added} comments, not 1.")
    log(f"POST {webhook.path} two times with one event ID adds one comment")
