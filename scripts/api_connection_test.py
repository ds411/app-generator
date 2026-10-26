"""Connect a user of a generated FastAPI app to an API at the mock OAuth server (ADR 0033).

The app is tests/fixtures/api-connections.yaml with the hand-written
logic of tests/fixtures/api-connections/extensions/: the operation
`sync_calendar` counts the events of the user of the client. The mock
server of `scripts/mock_api.py` serves the API `calendar` and the pages
of its authorization code flow. The test:

1. Signs up a user, and starts a connection with `return_to`. The page of
   the mock server sends the browser to the callback with a code, and the
   callback sends it to the page of `return_to` with `#connected=`.
2. Runs `sync_calendar`: the mock API gets the access token of the code.
3. Revokes the tokens at the mock server, and runs `sync_calendar` again:
   the client gets a new access token with the refresh token.
4. Runs one pass of the worker: the job `nightly_sync` calls the API with
   the token of the owner of the calendar.
5. A user without a connection gets 409. After the delete of the
   connection, the first user gets 409 too.

The test starts the app on the machine with its local database
(`scripts/smoke_test.py --local`). Run it from the repository root, after
the build of the app:

    uv run scripts/api_connection_test.py <definition> --app <folder>

scripts/check-fastapi.sh runs it.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any, cast

import smoke_test
from mock_api import MockApi

from appgen.dsl import AppDefinition, load_definition

FRONT_END = "http://localhost:5173"
PASSWORD = "correct-horse-battery"
WORKER_TIME = "2026-06-15T02:01:00Z"
"""A time of a pass of the worker: one minute after the schedule of `nightly_sync`."""


class CheckError(Exception):
    """A check of the connection failed."""


def log(message: str) -> None:
    print(f"api-connection-test: {message}", flush=True)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def call(
    method: str, url: str, body: object = None, token: str | None = None
) -> tuple[int, dict[str, str], str]:
    """Send a request without the redirects. Return the status, the headers (with lower case
    names), and the body."""
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(request, timeout=30) as response:
            return response.status, _lower(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, _lower(error.headers), error.read().decode(errors="replace")


def _lower(headers: Message) -> dict[str, str]:
    """Return the headers with lower case names."""
    return {name.lower(): value for name, value in headers.items()}


def expect(answer: tuple[int, dict[str, str], str], status: int, what: str) -> Any:
    """Check the status of an answer, and return its JSON body, or None without a body."""
    if answer[0] != status:
        raise CheckError(f"{what} gave {answer[0]}, not {status}: {answer[2][:500]}")
    log(f"{what} gives {status}")
    return json.loads(answer[2]) if answer[2] else None


def sign_up(base: str, name: str, email: str) -> tuple[str, str]:
    """Sign up a new user, and return the token and the user ID."""
    body = {"name": name, "email": email, "password": PASSWORD}
    token = expect(call("POST", f"{base}/auth/sign-up", body), 201, f"the sign-up of {email}")
    me = expect(call("GET", f"{base}/auth/me", token=token["access_token"]), 200, "GET /auth/me")
    return token["access_token"], me["id"]


def connect(base: str, mock: MockApi, token: str) -> None:
    """Do the steps of the browser: the start, the page of the mock server, and the callback."""
    page = f"{FRONT_END}/connections"
    link = expect(
        call("POST", f"{base}/auth/connections/calendar", {"return_to": page}, token),
        200,
        "POST /auth/connections/calendar",
    )
    url: str = link["authorization_url"]
    if not url.startswith(mock.base_url("calendar") + "/oauth/authorize?"):
        raise CheckError(f"The start gave {url}, not the page of the mock server.")
    status, headers, body = call("GET", url)
    if status != 302:
        raise CheckError(f"The page of the mock server gave {status}: {body}")
    callback = headers["location"]
    if not callback.startswith(f"{base}/auth/connections/calendar/callback?"):
        raise CheckError(f"The mock server sent the browser to {callback}.")
    status, headers, body = call("GET", callback)
    if status != 303 or headers["location"] != f"{page}#connected=calendar":
        raise CheckError(f"The callback gave {status} {headers.get('location')}: {body}")
    log("the callback sends the browser back to return_to with #connected=calendar")
    answer = call("GET", f"{base}/auth/connections", token=token)
    listed = expect(answer, 200, "GET /auth/connections")
    if [c["connected"] for c in listed if c["api"] == "calendar"] != [True]:
        raise CheckError(f"GET /auth/connections gave {listed}.")


def last_token(mock: MockApi) -> str:
    """Return the access token of the last call of the operation listEvents."""
    calls = cast(list[dict[str, Any]], mock.calls("calendar", "listEvents"))
    if not calls:
        raise CheckError("The mock API got no call of listEvents.")
    return str(calls[-1]["headers"].get("authorization", ""))


def grants(mock: MockApi) -> list[str]:
    """Return the grant type of each request of the token endpoint, in order."""
    calls = cast(list[dict[str, Any]], mock.calls("calendar", "token"))
    return [c.get("form", {}).get("grant_type", [""])[0] for c in calls]


def sync(base: str, calendar: str, token: str, status: int = 204) -> None:
    url = f"{base}/calendars/{calendar}/sync-calendar"
    expect(call("POST", url, token=token), status, f"POST /calendars/<id>/sync-calendar ({status})")


def events(base: str, calendar: str, token: str) -> int:
    record = expect(call("GET", f"{base}/calendars/{calendar}", token=token), 200, "GET /calendars")
    return int(record["events"])


def run_worker(app: Path, env: dict[str, str]) -> None:
    """Run one pass of the worker at a time of the schedule of the job."""
    command = ["uv", "run", "python", "-m", "app.worker", "--once", "--now", WORKER_TIME]
    subprocess.run(command, cwd=app, env=env, check=True)
    log(f"one pass of the worker at {WORKER_TIME}")


def api_connection_test(definition: AppDefinition, app: Path) -> None:
    base = f"http://localhost:{smoke_test.PORTS['fastapi']}"
    with (
        tempfile.TemporaryDirectory(prefix="appgen-api-connection.") as temp,
        MockApi(definition) as mock,
    ):
        env = mock.env() | mock.credentials()
        env |= {
            "AUTH_SECRET": "check-api-connections",
            "CORS_ORIGINS": json.dumps([FRONT_END]),
            "PUBLIC_URL": base,
            "LOG_JSON": "false",
        }
        with smoke_test.started_local("fastapi", app, Path(temp), env):
            try:
                smoke_test.wait_for("fastapi", base + "/health")
                token, user_id = sign_up(base, "Ada Lovelace", "ada@example.com")
                connect(base, mock, token)
                body = {"title": "Work", "owner_id": user_id}
                calendar = expect(
                    call("POST", f"{base}/calendars", body, token), 201, "POST /calendars"
                )["id"]

                sync(base, calendar, token)
                first = last_token(mock)
                if first != f"Bearer {mock.tokens[0]}" or events(base, calendar, token) != 2:
                    raise CheckError(f"The first call of the API sent {first}.")
                log("the API gets the access token of the code, and the record has 2 events")

                mock.revoke()
                sync(base, calendar, token)
                if grants(mock) != ["authorization_code", "refresh_token"]:
                    raise CheckError(f"The token endpoint got the grants {grants(mock)}.")
                if last_token(mock) != f"Bearer {mock.tokens[-1]}":
                    raise CheckError(f"The call after the revoke sent {last_token(mock)}.")
                log("after a 401, the client gets a new access token with the refresh token")

                count = len(mock.calls("calendar", "listEvents"))
                database = f"sqlite+aiosqlite:///{Path(temp) / 'local.db'}"
                worker_env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
                run_worker(app, worker_env | env | {"DATABASE_URL": database})
                calls = cast(list[dict[str, Any]], mock.calls("calendar", "listEvents"))[count:]
                sent = {c["headers"].get("authorization") for c in calls}
                if f"Bearer {mock.tokens[-1]}" not in sent:
                    raise CheckError(f"The job sent the tokens {sent}.")
                log("the job calls the API with the token of the owner of the calendar")

                other, _ = sign_up(base, "Grace Hopper", "grace@example.com")
                sync(base, calendar, other, 409)
                url = f"{base}/auth/connections/calendar"
                expect(call("DELETE", url, token=token), 204, "DELETE /auth/connections/calendar")
                sync(base, calendar, token, 409)
            except CheckError as error:
                # started_local prints the log of the app for a SmokeError.
                raise smoke_test.SmokeError(str(error)) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("definition", type=Path)
    parser.add_argument("--app", type=Path, required=True, help="The folder of the built app.")
    args = parser.parse_args()
    definition = load_definition(args.definition)
    try:
        api_connection_test(definition, args.app.resolve())
    except (smoke_test.SmokeError, subprocess.CalledProcessError) as error:
        print(f"api-connection-test: failed: {error}", file=sys.stderr)
        sys.exit(1)
    log("passed")


if __name__ == "__main__":
    main()
