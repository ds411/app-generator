"""Serve the third-party APIs of a definition with the examples of their OpenAPI documents.

The checks of the generated apps do not call the real APIs (ADR 0019).
This mock server answers each operation that the definition selects
with the example answer of the document, and records each request. It
serves each API under its name: the base URL of the API `holidays` is
`http://<host>:<port>/holidays`. A request for another path gets the
status 404. A text answer has the text of the example, and a binary
answer the bytes of `EXAMPLE_TEXT`.

An API with OAuth 2.0 and a token URL that is a path (for example
`/oauth/token`) gets a token endpoint under its base URL. The endpoint
gives a new token for each request (`mock-token-1`, `mock-token-2`, and
so on), and an operation of the API needs a token that the server gave
and did not revoke (`MockApi.revoke`, or `POST /_revoke`), else it gets
the status 401.

`GET /_requests` gives the recorded requests as JSON: the API, the
operation ID (`token` for a token request), the method, the path under
the base URL, the query, the headers (with lower case names), and the
fields of a form body (`form`) and the files of a multipart form
(`files`: the file name, the media type, and the content as text).
The answers allow all origins (CORS), so that a browser app can call
the server.

Run it from the repository root:

    uv run scripts/mock_api.py [definition] [--host 127.0.0.1] [--port 8430]

The other check scripts start it in a thread with `MockApi`.
"""

import argparse
import contextlib
import email.parser
import email.policy
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
from appgen.dsl.openapi import EXAMPLE_TEXT

DEFINITION = Path("examples/project-tracker/app.yaml")
SECRET = "check-secret"
"""The API key, the bearer token, or the client secret of each API with security."""
CLIENT_ID = "check-client"
"""The client ID of each API with OAuth 2.0."""


@dataclass(frozen=True, slots=True)
class Route:
    """An operation of an API, with its example answer."""

    api: str
    operation_id: str
    method: str
    pattern: re.Pattern[str]
    status: int
    example: object
    answer: str = "json"
    """`json`, `text`, or `binary`."""
    media: str = "application/json"
    """The content type of the answer."""
    secured: bool = False
    """True: the operation needs a token of the token endpoint of its API."""


def routes(definition: AppDefinition) -> list[Route]:
    """Return a route for each selected operation of each API of a definition."""
    found: list[Route] = []
    for name, api in definition.apis.items():
        secured = name in token_paths(definition)
        for operation in api.spec.operations:
            parts = re.split(r"(\{[^}]+\})", operation.path)
            regex = "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts)
            status = int(operation.status) if operation.status.isdigit() else 200
            media = operation.answer_media
            if "*" in media:
                media = "text/plain" if operation.answer == "text" else "application/octet-stream"
            found.append(
                Route(
                    api=name,
                    operation_id=operation.id,
                    method=operation.method.upper(),
                    pattern=re.compile(f"^{regex}$"),
                    status=status,
                    example=operation.example,
                    answer=operation.answer if operation.result is not None else "json",
                    media=media,
                    secured=secured,
                )
            )
    return found


def token_paths(definition: AppDefinition) -> dict[str, str]:
    """Return the path of the token URL of each API with OAuth 2.0 and a token URL that is a
    path, under the base URL of the API."""
    found: dict[str, str] = {}
    for name, api in definition.apis.items():
        document = api.openapi
        if api.security is None or document is None:
            continue
        scheme = document.security_schemes.get(api.security.scheme)
        if scheme is not None and scheme.type == "oauth2" and (scheme.token_url or "")[:1] == "/":
            found[name] = scheme.token_url or ""
    return found


class MockApi:
    """A mock server of the APIs of a definition, in a thread.

    Use it as a context manager: the server starts at the start of the
    block, and stops at the end.
    """

    def __init__(self, definition: AppDefinition, host: str = "127.0.0.1", port: int = 0) -> None:
        self.definition = definition
        self.routes = routes(definition)
        self.token_paths = token_paths(definition)
        self.requests: list[dict[str, object]] = []
        self.tokens: list[str] = []
        """The tokens that the token endpoints gave, in order."""
        self.revoked: set[str] = set()
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

    def credentials(self) -> dict[str, str]:
        """Return the environment variables of the credentials of the APIs: `SECRET` and
        `CLIENT_ID`."""
        found: dict[str, str] = {}
        for api in self.definition.apis.values():
            if api.security is not None:
                for key, env in api.security.variables:
                    found[env] = CLIENT_ID if key == "client_id_env" else SECRET
        return found

    def issue(self) -> str:
        """Return a new token of a token endpoint."""
        with self._lock:
            self.tokens.append(f"mock-token-{len(self.tokens) + 1}")
            return self.tokens[-1]

    def accepts(self, authorization: str | None) -> bool:
        """Return True for the header `Authorization` with a token that the server gave and did
        not revoke."""
        token = (authorization or "").removeprefix("Bearer ")
        with self._lock:
            return token in self.tokens and token not in self.revoked

    def revoke(self) -> None:
        """Revoke each token that the server gave: the next request with one gets 401."""
        with self._lock:
            self.revoked.update(self.tokens)

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

    def do_OPTIONS(self) -> None:
        """Answer the CORS preflight request of a browser."""
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def _cors(self) -> None:
        """Allow all origins, so that a browser app can call the mock server."""
        self.send_header("Access-Control-Allow-Origin", "*")

    def log_message(self, format: str, *args: object) -> None:
        """Write no log line for each request."""

    def _answer(self) -> None:
        mock = self.server_mock
        url = urllib.parse.urlsplit(self.path)
        if self.command == "GET" and url.path == "/_requests":
            self._send(200, mock.recorded())
            return
        if self.command == "POST" and url.path == "/_revoke":
            mock.revoke()
            self._send(204, None)
            return
        length = int(self.headers.get("Content-Length") or 0)
        content = self.rfile.read(length) if length else b""
        api, _, rest = url.path.lstrip("/").partition("/")
        path = "/" + rest
        token = self.command == "POST" and mock.token_paths.get(api) == path
        route = next(
            (
                r
                for r in mock.routes
                if r.api == api and r.method == self.command and r.pattern.match(path)
            ),
            None,
        )
        entry: dict[str, object] = {
            "api": api,
            "operation_id": "token" if token else route.operation_id if route else None,
            "method": self.command,
            "path": path,
            "query": urllib.parse.parse_qs(url.query),
            "headers": {name.lower(): value for name, value in self.headers.items()},
        }
        entry.update(_form(self.headers.get("Content-Type") or "", content))
        mock.record(entry)
        if token:
            answer = {"access_token": mock.issue(), "token_type": "Bearer", "expires_in": 3600}
            self._send(200, answer)
        elif route is None:
            self._send(404, {"detail": f"The mock has no operation for {self.command} {url.path}."})
        elif route.secured and not mock.accepts(self.headers.get("Authorization")):
            self._send(401, {"message": "The access token is missing or not valid."})
        elif route.answer == "text":
            self._send_bytes(route.status, str(route.example).encode(), route.media)
        elif route.answer == "binary":
            self._send_bytes(route.status, EXAMPLE_TEXT.encode(), route.media)
        else:
            self._send(route.status, route.example)

    def _send(self, status: int, data: object) -> None:
        if status == 204:
            self.send_response(status)
            self._cors()
            self.end_headers()
            return
        self._send_bytes(status, json.dumps(data).encode(), "application/json")

    def _send_bytes(self, status: int, body: bytes, media: str) -> None:
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _form(content_type: str, content: bytes) -> dict[str, object]:
    """Return the fields (`form`) and the files (`files`) of a form body, or nothing."""
    media = content_type.split(";")[0].strip().lower()
    if media == "application/x-www-form-urlencoded":
        return {"form": urllib.parse.parse_qs(content.decode(), keep_blank_values=True)}
    if media != "multipart/form-data":
        return {}
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + content)
    form: dict[str, list[str]] = {}
    files: dict[str, list[dict[str, str]]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        text = payload.decode() if isinstance(payload, bytes) else ""
        if not isinstance(name, str):
            continue
        filename = part.get_filename()
        if filename is None:
            form.setdefault(name, []).append(text)
        else:
            files.setdefault(name, []).append(
                {"filename": filename, "type": part.get_content_type(), "content": text}
            )
    return {"form": form, "files": files}


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
