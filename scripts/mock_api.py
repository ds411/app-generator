"""Serve the third-party APIs of a definition with the examples of their OpenAPI documents.

The checks of the generated apps do not call the real APIs (ADR 0019).
This mock server answers each operation that the definition selects
with the example answer of the document, and records each request. It
serves each API under its name: the base URL of the API `holidays` is
`http://<host>:<port>/holidays`. A request for another path gets the
status 404.

`GET /_requests` gives the recorded requests as JSON: the API, the
operation ID, the method, the path under the base URL, and the query.

Run it from the repository root:

    uv run scripts/mock_api.py [definition] [--host 127.0.0.1] [--port 8430]

The other check scripts start it in a thread with `MockApi`.
"""

import argparse
import contextlib
import json
import re
import sys
import threading
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Self

from appgen.dsl import AppDefinition, load_definition

DEFINITION = Path("examples/project-tracker/app.yaml")


@dataclass(frozen=True, slots=True)
class Route:
    """An operation of an API, with its example answer."""

    api: str
    operation_id: str
    method: str
    pattern: re.Pattern[str]
    status: int
    example: object


def routes(definition: AppDefinition) -> list[Route]:
    """Return a route for each selected operation of each API of a definition."""
    found: list[Route] = []
    for name, api in definition.apis.items():
        for operation in api.spec.operations:
            parts = re.split(r"(\{[^}]+\})", operation.path)
            regex = "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts)
            status = int(operation.status) if operation.status.isdigit() else 200
            found.append(
                Route(
                    api=name,
                    operation_id=operation.id,
                    method=operation.method.upper(),
                    pattern=re.compile(f"^{regex}$"),
                    status=status,
                    example=operation.example,
                )
            )
    return found


class MockApi:
    """A mock server of the APIs of a definition, in a thread.

    Use it as a context manager: the server starts at the start of the
    block, and stops at the end.
    """

    def __init__(self, definition: AppDefinition, host: str = "127.0.0.1", port: int = 0) -> None:
        self.definition = definition
        self.routes = routes(definition)
        self.requests: list[dict[str, object]] = []
        self._lock = threading.Lock()
        mock = self

        class Handler(_Handler):
            server_mock = mock

        self.server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def base_url(self, api: str, host: str = "localhost") -> str:
        return f"http://{host}:{self.port}/{api}"

    def env(self, host: str = "localhost") -> dict[str, str]:
        """Return the environment variables that point each API of the app to the mock server."""
        return {
            api.base_url_env: self.base_url(name, host)
            for name, api in self.definition.apis.items()
        }

    def record(self, entry: dict[str, object]) -> None:
        with self._lock:
            self.requests.append(entry)

    def recorded(self) -> list[dict[str, object]]:
        """Return a copy of the recorded requests."""
        with self._lock:
            return list(self.requests)

    def calls(self, api: str, operation_id: str) -> list[dict[str, object]]:
        """Return the recorded requests of an operation."""
        return [r for r in self.recorded() if r["api"] == api and r["operation_id"] == operation_id]

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Handler(BaseHTTPRequestHandler):
    server_mock: MockApi

    def do_GET(self) -> None:
        self._answer()

    def do_POST(self) -> None:
        self._answer()

    def do_PUT(self) -> None:
        self._answer()

    def do_PATCH(self) -> None:
        self._answer()

    def do_DELETE(self) -> None:
        self._answer()

    def log_message(self, format: str, *args: object) -> None:
        """Write no log line for each request."""

    def _answer(self) -> None:
        mock = self.server_mock
        url = urllib.parse.urlsplit(self.path)
        if self.command == "GET" and url.path == "/_requests":
            self._send(200, mock.recorded())
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        api, _, rest = url.path.lstrip("/").partition("/")
        path = "/" + rest
        route = next(
            (
                r
                for r in mock.routes
                if r.api == api and r.method == self.command and r.pattern.match(path)
            ),
            None,
        )
        mock.record(
            {
                "api": api,
                "operation_id": route.operation_id if route else None,
                "method": self.command,
                "path": path,
                "query": urllib.parse.parse_qs(url.query),
            }
        )
        if route is None:
            self._send(404, {"detail": f"The mock has no operation for {self.command} {url.path}."})
        else:
            self._send(route.status, route.example)

    def _send(self, status: int, data: object) -> None:
        if status == 204:
            self.send_response(status)
            self.end_headers()
            return
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("definition", nargs="?", type=Path, default=DEFINITION)
    parser.add_argument("--host", default="127.0.0.1", help="The address of the server.")
    parser.add_argument("--port", type=int, default=8430, help="The port of the server.")
    args = parser.parse_args()
    definition = load_definition(args.definition)
    if not definition.apis:
        print(f"mock-api: {args.definition} has no APIs.", file=sys.stderr)
        return 1
    with MockApi(definition, args.host, args.port) as mock:
        for name, value in mock.env().items():
            print(f"mock-api: {name}={value}", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
