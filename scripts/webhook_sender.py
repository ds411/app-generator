"""Sign and send webhooks to a generated app, as the sender of a webhook does (ADR 0028).

`sign` gives the headers of a signed request for a webhook of a
definition: an HMAC-SHA256 of the body in a header (`hmac_sha256`), or
the header `Stripe-Signature` with a time (`stripe`). `secrets` gives a
test secret for each webhook, as environment variables for the app.

The smoke test (`scripts/smoke_test.py`) starts the project tracker with
these secrets, and calls `check_commits`: it sends the event of the
webhook `commits` two times with a correct signature, one time with a
wrong signature, and one time with a body that does not agree with the
schema. With the FastAPI app, it checks that the hand-written logic of
the example adds one comment to the task.
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


@dataclass(frozen=True, slots=True)
class Email:
    """An inbound email for a webhook with `format: email` (ADR 0030)."""

    message_id: str | None
    subject: str = "The export does not work"
    sender: tuple[str, str] = ("Ada Lovelace", "ada@example.com")
    receiver: str = "support@example.com"
    text: str = "The export button does nothing."
    in_reply_to: str | None = None
    attachment: tuple[str, bytes, str] = ("screen.png", b"\x89PNG\r\n", "image/png")


def email_request(
    webhook: Webhook, email: Email, secret: str, at: int | None = None
) -> tuple[bytes, dict[str, str]]:
    """Return the body and the headers of the request of the mail service of the webhook."""
    sender = f"{email.sender[0]} <{email.sender[1]}>"
    headers: dict[str, str] = {}
    if webhook.signature.scheme == "basic":
        headers["Authorization"] = "Basic " + base64.b64encode(secret.encode()).decode()
    if webhook.provider == "postmark":
        extra = [("Message-ID", email.message_id), ("In-Reply-To", email.in_reply_to)]
        data = {
            "From": sender,
            "FromFull": {"Email": email.sender[1], "Name": email.sender[0]},
            "To": email.receiver,
            "ToFull": [{"Email": email.receiver, "Name": ""}],
            "CcFull": [],
            "Subject": email.subject,
            "TextBody": email.text,
            "HtmlBody": f"<p>{email.text}</p>",
            "Headers": [{"Name": name, "Value": value} for name, value in extra if value],
            "Attachments": [
                {
                    "Name": email.attachment[0],
                    "Content": base64.b64encode(email.attachment[1]).decode(),
                    "ContentType": email.attachment[2],
                    "ContentLength": len(email.attachment[1]),
                }
            ],
        }
        headers["Content-Type"] = "application/json"
        return json.dumps(data).encode(), headers
    lines = [("To", email.receiver), ("Subject", email.subject)]
    lines += [
        (name, value)
        for name, value in [("Message-ID", email.message_id), ("In-Reply-To", email.in_reply_to)]
        if value
    ]
    if webhook.provider == "mailgun":
        fields = {
            "recipient": email.receiver,
            "sender": email.sender[1],
            "from": sender,
            "subject": email.subject,
            "body-plain": email.text,
            "body-html": f"<p>{email.text}</p>",
            "message-headers": json.dumps([[name, value] for name, value in lines]),
            "attachment-count": "1",
        }
        if webhook.signature.scheme == "mailgun":
            timestamp = str(int(time.time()) if at is None else at)
            token = hashlib.sha256(f"{email.message_id}{timestamp}".encode()).hexdigest()[:50]
            digest = hmac.new(secret.encode(), (timestamp + token).encode(), hashlib.sha256)
            fields |= {"timestamp": timestamp, "token": token, "signature": digest.hexdigest()}
        file_field = "attachment-1"
    else:
        fields = {
            "headers": "".join(f"{name}: {value}\n" for name, value in lines),
            "from": sender,
            "to": email.receiver,
            "subject": email.subject,
            "text": email.text,
            "html": f"<p>{email.text}</p>",
            "envelope": json.dumps({"to": [email.receiver], "from": email.sender[1]}),
            "attachments": "1",
        }
        file_field = "attachment1"
    body, content_type = multipart(fields, {file_field: email.attachment})
    headers["Content-Type"] = content_type
    return body, headers


def multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    """Return the body and the content type of a multipart form."""
    boundary = "appgen-" + hashlib.sha256(json.dumps(fields).encode()).hexdigest()[:24]
    parts: list[bytes] = []
    for name, value in fields.items():
        head = f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        parts.append(f"--{boundary}\r\n{head}".encode() + value.encode() + b"\r\n")
    for name, (filename, content, media_type) in files.items():
        head = (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n"
        )
        parts.append(f"--{boundary}\r\n{head}".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


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
    comments: Callable[[], int] | None,
    log: Callable[[str], None],
) -> None:
    """Send the event of the webhook `commits` of the project tracker, and check the comments.

    `comments` gives the number of comments of the task, or None if the
    app has no endpoint for it. A correct signature adds one comment, also
    when the event comes again, a wrong signature gives 401 and no
    comment, and a task ID that is not a UUID gives 422.
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
    before = comments() if comments else 0
    wrong = send(url, body, sign(webhook, body, "a-wrong-secret"))
    if wrong.status != 401:
        raise WebhookError(f"POST {webhook.path} with a wrong signature gave {wrong.status}.")
    if comments and comments() != before:
        raise WebhookError(f"POST {webhook.path} with a wrong signature added a comment.")
    log(f"POST {webhook.path} with a wrong signature gives 401")
    invalid = json.dumps({**event, "id": f"evt-invalid-{task_id}", "task_id": "T-1"}).encode()
    answer = send(url, invalid, sign(webhook, invalid, secret))
    if answer.status != 422:
        raise WebhookError(f"POST {webhook.path} with a task ID 'T-1' gave {answer.status}.")
    log(f"POST {webhook.path} with a body that does not agree with the schema gives 422")
    for repeated in (False, True):
        answer = send(url, body, sign(webhook, body, secret))
        if answer.status != 200:
            raise WebhookError(f"POST {webhook.path} gave {answer.status}: {answer.body}")
        receipt = json.loads(answer.body)
        if receipt.get("repeated") is not repeated:
            raise WebhookError(f"POST {webhook.path} gave {receipt}, not repeated={repeated}.")
    if comments is None:
        log(f"POST {webhook.path} two times with one event ID runs the logic one time")
        return
    added = comments() - before
    if added != 1:
        raise WebhookError(f"Two deliveries of one event added {added} comments, not 1.")
    log(f"POST {webhook.path} two times with one event ID adds one comment")
