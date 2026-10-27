"""A mock server of the API v2 of Amazon SES for the checks of `auth.delivery: ses`.

The server answers `POST /v2/email/outbound-emails` (`SendEmail`) with a
new message ID. It checks that the request has an `Authorization` header
of AWS Signature Version 4 with the access key ID `ACCESS_KEY_ID`, for
the service `ses`, else it answers 403. It does not check the signature.
It keeps each message with simple content in its memory, and also writes
it as one JSON line to a file (`--out`): the sender, the recipients, the
subject, and the text, as scripts/mock_smtp.py does. At the start, it
empties the file. A recipient in the domain `REJECTED_DOMAIN` gets the
error `MessageRejected` (400), as an address that the sandbox of SES does
not allow. It uses only the standard library.

Run it from the repository root:

    uv run scripts/mock_ses.py [--port 4566] [--out messages.jsonl]

Set `AWS_ENDPOINT_URL_SESV2=http://127.0.0.1:<port>`, `AWS_REGION`,
`AWS_ACCESS_KEY_ID=<ACCESS_KEY_ID>`, and any `AWS_SECRET_ACCESS_KEY` in
the app (see `app_env`): the AWS SDKs of Python and JavaScript read the
endpoint of SES from `AWS_ENDPOINT_URL_SESV2`. Stop the server with
Ctrl-C. `scripts/auth_ui_test.py` starts it in a thread.
"""

import argparse
import json
import re
import threading
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_PORT = 4566
ACCESS_KEY_ID = "AKIAMOCKSES000000000"
"""The access key ID that the server accepts. The secret access key can be any text."""
SECRET_ACCESS_KEY = "mock-ses-secret"
REGION = "us-east-1"
REJECTED_DOMAIN = "rejected.example.com"
"""The domain of the recipients that the server does not accept (`MessageRejected`)."""
PATH = "/v2/email/outbound-emails"
_AUTHORIZATION = re.compile(
    r"AWS4-HMAC-SHA256 Credential=(?P<key>[^/]+)/\d{8}/(?P<region>[^/]+)/(?P<service>[^/]+)/"
    r"aws4_request, SignedHeaders=[^,]+, Signature=[0-9a-f]{64}$"
)


def app_env(port: int) -> dict[str, str]:
    """Return the environment variables of an app that sends its email to the server."""
    return {
        "AWS_ENDPOINT_URL_SESV2": f"http://127.0.0.1:{port}",
        "AWS_REGION": REGION,
        "AWS_ACCESS_KEY_ID": ACCESS_KEY_ID,
        "AWS_SECRET_ACCESS_KEY": SECRET_ACCESS_KEY,
        "SES_FROM": "no-reply@example.com",
    }


@dataclass
class Outbox:
    """The messages that the server received, and the file that gets a copy of each."""

    out: Path | None = None
    messages: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    lock: threading.Lock = field(default_factory=threading.Lock)
    port: int = 0
    """The port of the server: with port 0, the system chooses a free port."""
    count: int = 0

    def add(self, request: dict[str, Any]) -> str:
        """Keep a message: the sender, the recipients, the subject, and the text. Return its ID."""
        simple = request.get("Content", {}).get("Simple", {})
        message: dict[str, object] = {
            "from": request.get("FromEmailAddress", ""),
            "to": list(request.get("Destination", {}).get("ToAddresses", [])),
            "subject": simple.get("Subject", {}).get("Data", ""),
            "text": simple.get("Body", {}).get("Text", {}).get("Data", ""),
        }
        if request.get("ConfigurationSetName"):
            message["configuration_set"] = request["ConfigurationSetName"]
        with self.lock:
            self.count += 1
            self.messages.append(message)
            if self.out is not None:
                with self.out.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(message) + "\n")
            return f"mock-ses-{self.count}"


def _handler(outbox: Outbox) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def answer(self, status: int, data: dict[str, object], error: str | None = None) -> None:
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-amzn-RequestId", "mock-ses-request")
            if error is not None:
                self.send_header("x-amzn-ErrorType", error)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            content = self.rfile.read(length) if length else b""
            if self.path.split("?")[0] != PATH:
                self.answer(404, {"message": f"The mock has no operation for {self.path}."})
                return
            match = _AUTHORIZATION.match(self.headers.get("Authorization") or "")
            if match is None or match["key"] != ACCESS_KEY_ID or match["service"] != "ses":
                message = "The security token included in the request is invalid."
                self.answer(403, {"message": message}, "UnrecognizedClientException")
                return
            try:
                request: dict[str, Any] = json.loads(content or b"{}")
            except json.JSONDecodeError:
                self.answer(400, {"message": "The body is not JSON."}, "BadRequestException")
                return
            recipients = request.get("Destination", {}).get("ToAddresses", [])
            if any(str(to).endswith("@" + REJECTED_DOMAIN) for to in recipients):
                message = "Email address is not verified."
                self.answer(400, {"message": message}, "MessageRejected")
                return
            self.answer(200, {"MessageId": outbox.add(request)})

    return Handler


@contextmanager
def serving(port: int = DEFAULT_PORT, out: Path | None = None) -> Generator[Outbox]:
    """Run the mock SES server in a thread, and stop it at the end."""
    if out is not None:
        out.write_text("")
    outbox = Outbox(out)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(outbox))
    server.daemon_threads = True
    outbox.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield outbox
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--out", type=Path, help="A file that gets each message as a JSON line.")
    args = parser.parse_args()
    with serving(args.port, args.out):
        print(f"mock-ses: the server on 127.0.0.1:{args.port} is ready.", flush=True)
        with suppress(KeyboardInterrupt):
            threading.Event().wait()


if __name__ == "__main__":
    main()
