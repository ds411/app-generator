"""Send inbound emails of each mail service to the webhooks of a generated app (ADR 0030).

The app is tests/fixtures/inbound-email.yaml with the hand-written logic
of tests/fixtures/inbound-email/extensions/: a new email makes a ticket,
and a reply (`In-Reply-To`) counts on the ticket of the email that it
answers. A reply to an email without a ticket gives 404. For each
webhook, the test sends an email in the format of its mail service
(`scripts/webhook_sender.py`), and checks:

1. A wrong secret gives 401, and with Mailgun an old signature too.
2. A new email gives 200, and the same `Message-ID` again gives
   `"repeated": true`.
3. A reply to the email gives 200, so the logic found the ticket of the
   first email. A reply to an unknown email gives 404.
4. FastAPI: the list of the tickets has the ticket with one reply.

The test starts the app on the machine with its local database
(`scripts/smoke_test.py --local`) and a test secret for each webhook.
Run it from the repository root, after the build of the app:

    uv run scripts/inbound_email_test.py <binding> <definition> --app <folder>

scripts/check-fastapi.sh and scripts/check-nextjs.sh run it.
"""

import argparse
import json
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

import smoke_test
import webhook_sender
from webhook_sender import Email

from appgen.dsl import AppDefinition, load_definition
from appgen.dsl.webhooks import Webhook

OLD = 3600
"""The age in seconds of an old signature: more than the tolerance of the fixture."""


class InboundEmailError(Exception):
    """A check of an email webhook failed."""


def log(binding: str, message: str) -> None:
    print(f"inbound-email-test: {binding}: {message}", flush=True)


def credentials(webhook: Webhook, name: str) -> str:
    """Return the test secret of a webhook: a user name and a password for `basic`."""
    return f"appgen:test-{name}" if webhook.signature.scheme == "basic" else f"test-key-{name}"


def check_webhook(binding: str, base: str, name: str, webhook: Webhook, secret: str) -> str:
    """Send the emails of the steps in the module docstring. Return the Message-ID of the
    ticket."""
    url = base + webhook.path
    stamp = time.time_ns()
    first = Email(message_id=f"<new-{name}-{stamp}@mail.example.com>", subject=f"Help {name}")
    reply = Email(
        message_id=f"<reply-{name}-{stamp}@mail.example.com>",
        subject=f"Re: Help {name}",
        in_reply_to=first.message_id,
    )
    unknown = Email(
        message_id=f"<other-{name}-{stamp}@mail.example.com>",
        in_reply_to=f"<unknown-{stamp}@mail.example.com>",
    )

    def send(email: Email, key: str = secret, at: int | None = None) -> webhook_sender.Answer:
        body, headers = webhook_sender.email_request(webhook, email, key, at)
        return webhook_sender.send(url, body, headers)

    def expect(what: str, answer: webhook_sender.Answer, status: int) -> dict[str, object]:
        if answer.status != status:
            raise InboundEmailError(
                f"POST {webhook.path} {what} gave {answer.status}, not {status}: {answer.body}"
            )
        log(binding, f"POST {webhook.path} {what} gives {status}")
        return json.loads(answer.body) if status == 200 else {}

    wrong = "appgen:wrong" if webhook.signature.scheme == "basic" else "wrong-key"
    expect("with a wrong secret", send(first, wrong), 401)
    if webhook.signature.scheme == "mailgun":
        old = int(time.time()) - OLD
        expect("with an old signature", send(first, at=old), 401)
    receipt = expect("with a new email", send(first), 200)
    if receipt != {"event_id": first.message_id, "repeated": False}:
        raise InboundEmailError(f"POST {webhook.path} gave {receipt} for a new email.")
    again = expect("with the same email again", send(first), 200)
    if again.get("repeated") is not True:
        raise InboundEmailError(f"POST {webhook.path} gave {again} for a repeated email.")
    expect("with a reply to the email", send(reply), 200)
    expect("with a reply to an unknown email", send(unknown), 404)
    assert first.message_id is not None
    return first.message_id


def check_tickets(base: str, message_ids: list[str]) -> None:
    """Check that the FastAPI app has a ticket with one reply for each email."""
    for message_id in message_ids:
        answer = smoke_test.get(
            f"{base}/tickets?{urllib.parse.urlencode({'message_id': message_id})}"
        )
        if answer.status != 200:
            raise InboundEmailError(f"GET /tickets gave {answer.status}: {answer.body}")
        items = json.loads(answer.body)["items"]
        if [item["replies"] for item in items] != [1]:
            raise InboundEmailError(f"The ticket of {message_id} has not one reply: {items}.")
    log("fastapi", f"GET /tickets has {len(message_ids)} tickets with one reply")


def inbound_email_test(binding: str, definition: AppDefinition, app: Path) -> None:
    secrets = {
        webhook.signature.secret_env: credentials(webhook, name)
        for name, webhook in definition.webhooks.items()
    }
    base = f"http://localhost:{smoke_test.PORTS[binding]}"
    with (
        tempfile.TemporaryDirectory(prefix="appgen-inbound-email.") as temp,
        smoke_test.started_local(binding, app, Path(temp), secrets),
    ):
        try:
            smoke_test.wait_for(binding, base + "/health")
            found = [
                check_webhook(binding, base, name, webhook, secrets[webhook.signature.secret_env])
                for name, webhook in definition.webhooks.items()
                if webhook.email
            ]
            if binding == "fastapi":
                check_tickets(base, found)
        except InboundEmailError as error:
            # started_local prints the log of the app for a SmokeError.
            raise smoke_test.SmokeError(str(error)) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("binding", choices=["fastapi", "nextjs"])
    parser.add_argument("definition", type=Path)
    parser.add_argument("--app", type=Path, required=True, help="The folder of the built app.")
    args = parser.parse_args()
    definition = load_definition(args.definition)
    try:
        inbound_email_test(args.binding, definition, args.app.resolve())
    except smoke_test.SmokeError as error:
        print(f"inbound-email-test: failed: {error}", file=sys.stderr)
        sys.exit(1)
    log(args.binding, "passed")


if __name__ == "__main__":
    main()
