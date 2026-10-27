"""Connect a user to an API on the page `/connections` of the front ends (ADR 0033).

The test has two apps, each with the hand-written logic in the folder
`extensions` next to its definition:

- `calendar`: tests/fixtures/api-connections.yaml, an API with the
  authorization code flow. The operation `sync_calendar` counts the
  events of the signed-in user at the API `calendar`.
- `jira`: tests/fixtures/jira-accounts.yaml, an API with HTTP Basic and
  the credentials of each user (#487). The operation `file_issue` files
  an issue in Jira in the name of the signed-in user.

For each app and binding, the test:

1. Generates the app, installs it, lints it, builds it, and runs the
   trace check on it (`appgen check`). The binding `react-api` is the
   React app with `x-react-data: api` and the FastAPI app of the
   definition.
2. Starts the mock server of the API (scripts/mock_api.py), whose page of
   the authorization URL allows the access at once, and the app: Next.js
   with PGlite and the seed records, React with `vite preview` and its
   mock data, and react-api with the FastAPI app (SQLite, the seed
   records) and `vite preview`.
3. Runs the UI test `ui-tests/tests/connections.spec.ts`: a new user
   signs up, connects the account of the API on the page, runs the row
   action that calls the API (not with mock data), disconnects the
   account, and gets the message of the missing connection at the next
   run. For the API with HTTP Basic, the user first gives a wrong
   password, and the page shows the message of the check.
4. Checks the requests at the mock server: for `calendar`, the change
   of the code for the tokens, with the PKCE verifier, and the call of
   the API with the access token of the user. For `jira`, the check
   with the wrong password, and the calls of the API with the
   credentials of the user. The React app with mock data connects at
   once, and sends no request.

Run it from the repository root:

    uv run scripts/connection_ui_test.py [binding ...] [--app calendar|jira] [--out folder]

Without a binding, the script tests React, Next.js, and react-api.
Without `--app`, it tests both apps. It needs uv, pnpm, and the
Chromium of Playwright (see scripts/smoke_test.py).
It uses the ports 5450 (React), 3450 (Next.js), 5451 and 8450 (react-api),
and 9450 (the mock server of the API). It does not need Docker.

Environment variables:
    PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the test, instead of the one
                                  that Playwright installs. Without both, the test
                                  uses /opt/pw-browsers/chromium if it exists.
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for an app to start (default 180).
"""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from mock_api import BASIC_AUTHORIZATION, SECRET, USERNAME, MockApi
from smoke_test import expected_ui

from appgen.bindings.react.api_client import DATA_KEY
from appgen.dsl import AppDefinition, load_definition
from appgen.gen.naming import kebab

UI_TESTS = Path("ui-tests")
BINDINGS = ("react", "nextjs", "react-api")
PORTS = {"react": 5450, "nextjs": 3450, "react-api": 5451}
API_PORT = 8450
"""The port of the FastAPI app of the binding `react-api`."""
MOCK_PORT = 9450
"""The port of the mock server of the API."""
PASSWORD = "connection-ui-test-password"
AUTH_SECRET = "connection-ui-test-secret"


@dataclass(frozen=True)
class Case:
    """An app of the test: its definition, its hand-written logic, and the row action that calls
    the API, with the texts of its toasts."""

    name: str
    definition: Path
    extensions: Path
    sync: dict[str, str]


CASES = (
    Case(
        "calendar",
        Path("tests/fixtures/api-connections.yaml"),
        Path("tests/fixtures/api-connections/extensions"),
        {
            "path": "/calendars",
            "action": "Sync",
            "toast": "The calendar is synced.",
            "notConnected": "Connect an account of the API calendar first.",
        },
    ),
    Case(
        "jira",
        Path("tests/fixtures/jira-accounts.yaml"),
        Path("tests/fixtures/jira-accounts/extensions"),
        {
            "path": "/tickets",
            "action": "File in Jira",
            "toast": "The ticket has an issue in Jira.",
            "notConnected": "Connect an account of the API jira first.",
        },
    ),
)
WRONG_PASSWORD = "wrong-" + SECRET
"""A password that the mock server does not accept."""


class ConnectionUiTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"connection-ui-test: {binding}: {message}", flush=True)


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})})


def generate(case: Case, definition: Path, binding: str, app: Path) -> None:
    """Generate an app with the hand-written logic of the fixture: appgen keeps the files."""
    log(binding, f"generate {definition} in {app}")
    app.mkdir(parents=True, exist_ok=True)
    extensions = case.extensions / binding
    if extensions.is_dir():
        shutil.copytree(extensions, app, dirs_exist_ok=True)
    command = ["uv", "run", "--locked", "appgen", "generate", str(definition), "-b", binding]
    subprocess.run([*command, "-o", str(app)], check=True, stdout=subprocess.DEVNULL)


def build(binding: str, definition: Path, app: Path, env: dict[str, str] | None = None) -> None:
    """Install, lint, and build a front end, and run the trace check on it."""
    log(binding, "pnpm install, pnpm lint, pnpm build, and appgen check")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "lint", cwd=app)
    run("pnpm", "--silent", "build", cwd=app, env=env)
    command = ["uv", "run", "--locked", "appgen", "check", str(definition), str(app)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def wait_for(binding: str, url: str) -> None:
    """Wait until a URL answers with 200."""
    timeout = float(os.environ.get("APPGEN_SMOKE_TIMEOUT", "180"))
    deadline = time.monotonic() + timeout
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status == 200:
                    return
                last = f"status {response.status}"
        except (OSError, urllib.error.HTTPError) as error:
            last = str(error)
        time.sleep(1)
    raise ConnectionUiTestError(f"{binding}: {url} did not answer in {timeout:.0f} s ({last}).")


@contextmanager
def started(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> Generator[None]:
    """Start a server, and stop it at the end. Show the end of its log after an error."""
    log_file = cwd / "server.log"
    with log_file.open("w") as output:
        # A new session, so that the stop also ends the child processes of pnpm and uv.
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        yield
    except BaseException:
        print(f"--- the log of {name}:", file=sys.stderr)
        print(log_file.read_text()[-4000:], file=sys.stderr)
        raise
    finally:
        os.killpg(process.pid, 15)
        process.wait(timeout=30)


def api_env(mock: MockApi) -> dict[str, str]:
    """Return the environment variables of the API: the mock server, and its credentials."""
    return {**mock.env(host="127.0.0.1"), **mock.credentials()}


def expected_connections(case: Case, definition: AppDefinition, server: bool) -> dict[str, object]:
    """Return what the UI test of the connections expects of the app."""
    auth = definition.auth
    assert auth is not None and auth.sign_up is not None
    users = definition.entities[auth.user_entity]
    sign_up = [
        {
            "id": f"sign-up-{kebab(name)}",
            "value": "user{n}@example.com" if users.fields[name].type == "email" else "User {n}",
        }
        for name in auth.sign_up.fields
    ]
    return {
        "apis": [
            {
                "api": kebab(name),
                "title": str(api.label),
                "kind": "basic" if api.user_basic else "oauth",
                # Only a server checks the credentials.
                "rejected": f"The API {name} did not accept the user name and the password."
                if api.check_operation is not None and server
                else None,
            }
            for name, api in definition.apis.items()
            if api.per_user
        ],
        "credentials": {"username": USERNAME, "password": SECRET, "wrong": WRONG_PASSWORD},
        "signUp": sign_up,
        "password": PASSWORD,
        "sync": case.sync if server else None,
    }


def check_ui(case: Case, binding: str, definition: AppDefinition) -> None:
    """Run the UI test of the connections on the app that runs."""
    log(binding, "UI test of the connections (Playwright)")
    name = f"{binding}-{case.name}-connections"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    expected = {
        **expected_ui("react" if binding == "react-api" else binding, definition),
        "connections": expected_connections(case, definition, server=binding != "react"),
    }
    expected_file.write_text(json.dumps(expected, indent=2) + "\n")
    env = {
        "APPGEN_BASE_URL": f"http://localhost:{PORTS[binding]}",
        "APPGEN_UI_EXPECTED": str(expected_file),
        "APPGEN_UI_OUTPUT": str((UI_TESTS / "test-results" / name).resolve()),
    }
    with (UI_TESTS / ".install.lock").open("w") as lock:
        # Only one check at a time installs the packages of the UI tests.
        fcntl.flock(lock, fcntl.LOCK_EX)
        run("pnpm", "install", "--silent", "--frozen-lockfile", cwd=UI_TESTS)
    command = ["pnpm", "exec", "playwright", "test", "tests/connections.spec.ts"]
    run(*command, "--project", "light", cwd=UI_TESTS, env=env)


def check_requests(case: Case, binding: str, mock: MockApi) -> None:
    """Check the requests of the app at the mock server of the API."""
    if binding == "react":
        if mock.recorded():
            raise ConnectionUiTestError(f"{binding}: the app with mock data called the server.")
        return
    if case.name == "jira":
        check_credential_requests(binding, mock)
        return
    forms = [cast(dict[str, list[str]], c.get("form", {})) for c in mock.calls("calendar", "token")]
    grants = [form for form in forms if form.get("grant_type") == ["authorization_code"]]
    if not grants or not all(form.get("code_verifier") for form in grants):
        raise ConnectionUiTestError(f"{binding}: no grant of a code with a PKCE verifier.")
    calls = mock.calls("calendar", "listEvents")
    headers = [cast(dict[str, str], call["headers"]) for call in calls]
    tokens = {item.get("authorization", "") for item in headers}
    if not calls or not tokens <= {f"Bearer {token}" for token in mock.tokens}:
        raise ConnectionUiTestError(f"{binding}: the API got no access token of the user.")
    log(binding, f"the mock server got {len(grants)} grant(s) and {len(calls)} call(s) of the API")


def check_credential_requests(binding: str, mock: MockApi) -> None:
    """Check the calls of the API with HTTP Basic: the check with the wrong password and with the
    credentials of the user, and the calls of the row action (a new issue, or a comment on the
    issue of the ticket) with the credentials of the user."""
    checks = [cast(dict[str, str], c["headers"]) for c in mock.calls("jira", "getCurrentUser")]
    headers = [item.get("authorization", "") for item in checks]
    if BASIC_AUTHORIZATION not in headers or headers[0] == BASIC_AUTHORIZATION:
        raise ConnectionUiTestError(
            f"{binding}: no check with the wrong password, then the right one."
        )
    operations = ("createIssue", "addComment")
    found = [call for name in operations for call in mock.calls("jira", name)]
    calls = [cast(dict[str, str], call["headers"]) for call in found]
    if not calls or any(item.get("authorization") != BASIC_AUTHORIZATION for item in calls):
        raise ConnectionUiTestError(f"{binding}: the API got no credentials of the user.")
    log(binding, f"the mock server got {len(checks)} check(s) and {len(calls)} call(s) of the API")


def nextjs_test(case: Case, definition: AppDefinition, out: Path) -> None:
    binding, app = "nextjs", out / f"{case.name}-nextjs"
    generate(case, case.definition, binding, app)
    build(binding, case.definition, app)
    run("pnpm", "--silent", "db:generate", cwd=app)
    port = str(PORTS[binding])
    with MockApi(definition, port=MOCK_PORT) as mock:
        env = {
            **os.environ,
            "PORT": port,
            "DATABASE_URL": f"pglite:{app / '.pglite'}",
            "DATABASE_MIGRATE": "true",
            "DATABASE_SEED": "true",
            "SEED_PASSWORD": PASSWORD,
            "AUTH_SECRET": AUTH_SECRET,
            "PUBLIC_URL": f"http://localhost:{port}",
            **api_env(mock),
        }
        with started(binding, ["pnpm", "--silent", "start"], app, env):
            wait_for(binding, f"http://localhost:{port}/sign-in")
            check_ui(case, binding, definition)
        check_requests(case, binding, mock)


def react_test(case: Case, definition: AppDefinition, out: Path) -> None:
    binding, app = "react", out / f"{case.name}-react"
    generate(case, case.definition, binding, app)
    build(binding, case.definition, app)
    port = str(PORTS[binding])
    command = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    with MockApi(definition, port=MOCK_PORT) as mock:
        with started(binding, command, app, {**os.environ, "PORT": port}):
            wait_for(binding, f"http://localhost:{port}/sign-in")
            check_ui(case, binding, definition)
        check_requests(case, binding, mock)


def react_api_test(case: Case, definition: AppDefinition, out: Path) -> None:
    """The React app with the FastAPI app: the page uses the routes of the FastAPI app."""
    binding = "react-api"
    marker = "\napp:\n"
    text = case.definition.read_text()
    if marker not in text:
        raise ConnectionUiTestError(f"{case.definition} has no 'app:' line.")
    text = text.replace(marker, f"{marker}  {DATA_KEY}: api\n", 1)
    # The copy is in another folder: the paths of the OpenAPI documents become absolute.
    folder = case.definition.parent.resolve()
    for name, api in definition.apis.items():
        old = f"document: {api.document}"
        if old not in text:
            raise ConnectionUiTestError(f"{case.definition}: the API {name} has no line '{old}'.")
        text = text.replace(old, f"document: {folder / api.document}")
    source = out / f"{case.name}-react-api.yaml"
    source.write_text(text)
    api, web = out / f"{case.name}-react-api-fastapi", out / f"{case.name}-{binding}"
    generate(case, source, "fastapi", api)
    generate(case, source, "react", web)
    log(binding, "uv sync")
    # The FastAPI app has its own virtual environment.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    subprocess.run(["uv", "sync", "--quiet"], cwd=api, env=env, check=True)
    api_url = f"http://127.0.0.1:{API_PORT}"
    build(binding, source, web, env={"VITE_API_URL": api_url})
    port = str(PORTS[binding])
    with MockApi(definition, port=MOCK_PORT) as mock:
        env |= {
            "DATABASE_URL": f"sqlite+aiosqlite:///{api / 'local.db'}",
            "DATABASE_SEED": "true",
            "AUTH_SECRET": AUTH_SECRET,
            "CORS_ORIGINS": json.dumps([f"http://localhost:{port}"]),
            "PUBLIC_URL": api_url,
            "LOG_JSON": "false",
            **api_env(mock),
        }
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=api, env=env, check=True)
        fastapi = ["uv", "run", "fastapi", "run", "app/main.py", "--port", str(API_PORT)]
        preview = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
        with (
            started("the FastAPI app", fastapi, api, env),
            started(binding, preview, web, {**os.environ, "PORT": port}),
        ):
            wait_for(binding, f"{api_url}/health")
            wait_for(binding, f"http://localhost:{port}/sign-in")
            check_ui(case, binding, definition)
        check_requests(case, binding, mock)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("bindings", nargs="*", metavar="binding", help=", ".join(BINDINGS))
    parser.add_argument(
        "--app", choices=[case.name for case in CASES], help="Only this app; the default is all."
    )
    parser.add_argument(
        "--out", type=Path, help="The folder of the apps; the default is a new one."
    )
    args = parser.parse_args()
    bindings: list[str] = args.bindings or list(BINDINGS)
    unknown = [b for b in bindings if b not in BINDINGS]
    if unknown:
        parser.error(f"unknown binding: {', '.join(unknown)}")
    cases = [case for case in CASES if args.app in (None, case.name)]
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-connection-ui.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    out.mkdir(parents=True, exist_ok=True)
    tests = {"react": react_test, "nextjs": nextjs_test, "react-api": react_api_test}
    try:
        for case in cases:
            definition = load_definition(case.definition)
            for binding in bindings:
                tests[binding](case, definition, out)
                log(binding, f"passed ({case.name})")
    except (ConnectionUiTestError, subprocess.CalledProcessError) as error:
        print(f"connection-ui-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
