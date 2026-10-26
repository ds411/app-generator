"""Send signed events to each webhook of a generated Next.js app (ADR 0028).

The logic of each webhook is the stub of its extension file, which
refuses each event with the status 501. Thus the test checks the
generated part of each endpoint for each kind of signature:

1. A wrong signature gives 401, and with the scheme `stripe`, an old
   signature too.
2. A body without the event ID, or a request without the header of the
   event ID, gives 400.
3. With a schema of the body, a body with only the event ID gives 422
   when the schema needs more properties.
4. A correct event reaches the logic (501). The endpoint then forgets
   the event, so the same event reaches the logic again (501, not a
   repeated event).

The test starts the app with PGlite in a temporary folder and a test
secret for each webhook (`scripts/webhook_sender.py`). Run it from the
repository root, after `pnpm install` and `pnpm build` in the app:

    uv run scripts/webhook_test.py <definition> --app <folder>

scripts/check-nextjs.sh runs it for tests/fixtures/webhooks.yaml. It
needs pnpm, but not Docker.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

import webhook_sender

from appgen.bindings.shared.webhooks import TEST_EVENT_ID, event_id_value, sample_event
from appgen.dsl import AppDefinition, load_definition
from appgen.dsl.webhooks import Webhook

PORT = 3060
"""The port of the app. The other checks that run at the same time use other ports."""
OLD = 3600
"""The age in seconds of an old signature: more than the tolerance of the fixture."""


class WebhookTestError(Exception):
    """A check of a webhook failed."""


def log(message: str) -> None:
    print(f"webhook-test: {message}", flush=True)


def wait_for(url: str, timeout: float = 120) -> None:
    """Wait until a URL answers with 200."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status == 200:
                    return
        except OSError, urllib.error.HTTPError:
            pass
        time.sleep(1)
    raise WebhookTestError(f"{url} did not answer in {timeout:.0f} seconds.")


def expect(webhook: Webhook, what: str, answer: webhook_sender.Answer, status: int) -> None:
    if answer.status != status:
        raise WebhookTestError(
            f"POST {webhook.path} {what} gave {answer.status}, not {status}: {answer.body}"
        )
    log(f"POST {webhook.path} {what} gives {status}")


def check_webhook(webhook: Webhook, base: str, secret: str) -> None:
    """Send the events of the steps in the module docstring to one webhook."""
    url = base + webhook.path
    sample = sample_event(webhook)
    body = json.dumps(sample).encode()
    event_header = webhook.event_id.header

    def signed(data: bytes, key: str = secret, at: int | None = None) -> dict[str, str]:
        headers = webhook_sender.sign(webhook, data, key, at)
        if event_header:
            headers[event_header] = TEST_EVENT_ID
        return headers

    send = webhook_sender.send
    expect(webhook, "with a wrong signature", send(url, body, signed(body, "wrong")), 401)
    changed = send(url, body + b" ", signed(body))
    expect(webhook, "with a changed body", changed, 401)
    if webhook.signature.scheme == "stripe":
        old = signed(body, at=int(time.time()) - OLD)
        expect(webhook, "with an old signature", send(url, body, old), 401)
    if event_header:
        headers = signed(body)
        del headers[event_header]
        expect(webhook, "without the event ID", send(url, body, headers), 400)
    else:
        empty = b"{}"
        expect(webhook, "without the event ID", send(url, empty, signed(empty)), 400)
    if webhook.body is not None and not event_header:
        only_id = json.dumps(_only_event_id(webhook, sample)).encode()
        if only_id != body:
            answer = send(url, only_id, signed(only_id))
            expect(webhook, "with only the event ID", answer, 422)
    for when in ("one time", "again"):
        answer = send(url, body, signed(body))
        expect(webhook, f"with a correct signature ({when})", answer, 501)


def _only_event_id(webhook: Webhook, sample: dict[str, object]) -> dict[str, object]:
    """Return a body with only the event ID of the sample."""
    data: object = event_id_value(webhook, sample)
    for name in reversed(webhook.event_id.path):
        data = {name: data}
    return cast(dict[str, object], data)


def webhook_test(definition: AppDefinition, app: Path) -> None:
    secrets = webhook_sender.secrets(definition)
    if not (app / "drizzle").is_dir():
        log("pnpm db:generate")
        subprocess.run(
            ["pnpm", "--silent", "db:generate"], cwd=app, check=True, stdout=subprocess.DEVNULL
        )
    with tempfile.TemporaryDirectory(prefix="appgen-webhook-test.") as temp:
        env = {
            **os.environ,
            **secrets,
            "PORT": str(PORT),
            "DATABASE_URL": f"pglite:{Path(temp) / 'pglite'}",
            "DATABASE_MIGRATE": "true",
        }
        output = Path(temp) / "app.log"
        log(f"pnpm start on port {PORT}")
        with output.open("w") as out:
            # A new session, so that the stop also ends the child processes of pnpm.
            process = subprocess.Popen(
                ["pnpm", "--silent", "start"],
                cwd=app,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            base = f"http://localhost:{PORT}"
            wait_for(base + "/health")
            for webhook in definition.webhooks.values():
                check_webhook(webhook, base, secrets[webhook.signature.secret_env])
        except WebhookTestError:
            print(output.read_text(), flush=True)
            raise
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("definition", type=Path)
    parser.add_argument("--app", type=Path, required=True, help="The folder of the built app.")
    args = parser.parse_args()
    definition = load_definition(args.definition)
    try:
        webhook_test(definition, args.app.resolve())
    except WebhookTestError as error:
        print(f"webhook-test: failed: {error}", file=sys.stderr)
        sys.exit(1)
    log("passed")


if __name__ == "__main__":
    main()
