"""A mock SMTP server for the checks of the delivery by SMTP (`auth.delivery: smtp`).

The server accepts each message without a sign-in and without TLS. It
keeps each message in its memory, and also writes it as one JSON line to
a file (`--out`): the sender, the recipients, the subject, and the text.
At the start, it empties the file. It uses only the standard library:
Python 3.12 and later have no module `smtpd`.

Run it from the repository root:

    uv run scripts/mock_smtp.py [--port 2525] [--out messages.jsonl]

Set `SMTP_HOST=127.0.0.1`, `SMTP_PORT=<port>`, and `SMTP_TLS=none` in the
app. Stop the server with Ctrl-C. `scripts/auth_ui_test.py` starts it in
a thread.
"""

import argparse
import json
import socketserver
import threading
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from pathlib import Path

DEFAULT_PORT = 2525
MAX_LINE_BYTES = 1_000_000


@dataclass
class Mailbox:
    """The messages that the server received, and the file that gets a copy of each."""

    out: Path | None = None
    messages: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    lock: threading.Lock = field(default_factory=threading.Lock)
    port: int = 0
    """The port of the server: with port 0, the system chooses a free port."""

    def add(self, sender: str, recipients: list[str], data: bytes) -> None:
        """Keep a message: the envelope, the subject, and the plain text."""
        parsed = message_from_bytes(data, policy=policy.default)
        body = parsed.get_body(preferencelist=("plain",))
        text: str = body.get_content() if body is not None else ""  # pyright: ignore[reportAttributeAccessIssue]
        message: dict[str, object] = {
            "from": sender,
            "to": recipients,
            "subject": str(parsed.get("Subject", "")),
            # SMTP ends each line with CRLF.
            "text": text.replace("\r\n", "\n"),
        }
        with self.lock:
            self.messages.append(message)
            if self.out is not None:
                with self.out.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(message) + "\n")


def _address(line: str) -> str:
    """Return the address of `MAIL FROM:<...>` or `RCPT TO:<...>`."""
    start, end = line.find("<"), line.find(">")
    return line[start + 1 : end] if 0 <= start < end else line.partition(":")[2].strip()


def _handler(mailbox: Mailbox) -> type[socketserver.StreamRequestHandler]:
    class Handler(socketserver.StreamRequestHandler):
        def reply(self, line: str) -> None:
            self.wfile.write(f"{line}\r\n".encode())

        def data(self) -> bytes:
            """Read the lines of a message until the line with one dot (RFC 5321)."""
            lines: list[bytes] = []
            while raw := self.rfile.readline(MAX_LINE_BYTES):
                if raw in (b".\r\n", b".\n"):
                    break
                # A line of the message that starts with a dot has one more dot.
                lines.append(raw[1:] if raw.startswith(b".") else raw)
            return b"".join(lines)

        def handle(self) -> None:
            self.reply("220 mock-smtp is ready")
            sender, recipients = "", list[str]()
            while raw := self.rfile.readline(MAX_LINE_BYTES):
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                verb = line[:4].upper()
                if verb == "EHLO":
                    self.reply("250-mock-smtp")
                    self.reply("250-8BITMIME")
                    self.reply("250 SMTPUTF8")
                elif verb == "HELO":
                    self.reply("250 mock-smtp")
                elif verb == "MAIL":
                    sender, recipients = _address(line), []
                    self.reply("250 OK")
                elif verb == "RCPT":
                    recipients.append(_address(line))
                    self.reply("250 OK")
                elif verb == "DATA":
                    self.reply("354 End the message with a line with one dot")
                    mailbox.add(sender, recipients, self.data())
                    self.reply("250 OK: the message is kept")
                elif verb in ("RSET", "NOOP"):
                    if verb == "RSET":
                        sender, recipients = "", []
                    self.reply("250 OK")
                elif verb == "QUIT":
                    self.reply("221 Bye")
                    return
                else:
                    self.reply("502 The server does not know this command")

    return Handler


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@contextmanager
def serving(port: int = DEFAULT_PORT, out: Path | None = None) -> Generator[Mailbox]:
    """Run the mock SMTP server in a thread, and stop it at the end."""
    if out is not None:
        out.write_text("")
    mailbox = Mailbox(out)
    server = _Server(("127.0.0.1", port), _handler(mailbox))
    mailbox.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield mailbox
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--out", type=Path, help="A file that gets each message as a JSON line.")
    args = parser.parse_args()
    with serving(args.port, args.out):
        print(f"mock-smtp: the server on 127.0.0.1:{args.port} is ready.", flush=True)
        with suppress(KeyboardInterrupt):
            threading.Event().wait()


if __name__ == "__main__":
    main()
