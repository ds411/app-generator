"""Connect a user to an API on the page `/connections` of the front ends (ADR 0033).

The app is tests/fixtures/api-connections.yaml with the hand-written
logic of tests/fixtures/api-connections/extensions/: the operation
`sync_calendar` counts the events of the signed-in user at the API
`calendar`. For each binding, the test:

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
   signs up, connects the account of the API on the page, syncs a
   calendar with the row action (not with mock data), disconnects the
   account, and gets the message of the missing connection at the next
   sync.
4. Checks the requests at the mock server: the change of the code for
   the tokens, with the PKCE verifier, and the call of the API with the
   access token of the user. The React app with mock data connects at
   once, and sends no request.

Run it from the repository root:

    uv run scripts/connection_ui_test.py [binding ...] [--out folder]

Without a binding, the script tests React, Next.js, and react-api. It
needs uv, pnpm, and the Chromium of Playwright (see scripts/smoke_test.py).
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
from pathlib import Path
from typing import cast

from mock_api import MockApi
from smoke_test import expected_ui

from appgen.bindings.react.api_client import DATA_KEY
from appgen.dsl import AppDefinition, load_definition
from appgen.gen.naming import kebab

DEFINITION = Path("tests/fixtures/api-connections.yaml")
EXTENSIONS = Path("tests/fixtures/api-connections/extensions")
UI_TESTS = Path("ui-tests")
BINDINGS = ("react", "nextjs", "react-api")
PORTS = {"react": 5450, "nextjs": 3450, "react-api": 5451}
API_PORT = 8450
"""The port of the FastAPI app of the binding `react-api`."""
MOCK_PORT = 9450
"""The port of the mock server of the API."""
PASSWORD = "connection-ui-test-password"
AUTH_SECRET = "connection-ui-test-secret"
SYNC = {
    "path": "/calendars",
    "action": "Sync",
    "toast": "The calendar is synced.",
    "notConnected": "Connect an account of the API calendar first.",
}
"""The row action that calls the API, and the texts of its toasts."""


class ConnectionUiTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"connection-ui-test: {binding}: {message}", flush=True)


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})})


def generate(definition: Path, binding: str, app: Path) -> None:
    """Generate an app with the hand-written logic of the fixture: appgen keeps the files."""
    log(binding, f"generate {definition} in {app}")
    app.mkdir(parents=True, exist_ok=True)
    extensions = EXTENSIONS / binding
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


def expected_connections(definition: AppDefinition, server: bool) -> dict[str, object]:
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
            {"api": kebab(name), "title": str(api.label)}
            for name, api in definition.apis.items()
            if api.user_flow
        ],
        "signUp": sign_up,
        "password": PASSWORD,
        "sync": SYNC if server else None,
    }


def check_ui(binding: str, definition: AppDefinition) -> None:
    """Run the UI test of the connections on the app that runs."""
    log(binding, "UI test of the connections (Playwright)")
    name = f"{binding}-connections"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    expected = {
        **expected_ui("react" if binding == "react-api" else binding, definition),
        "connections": expected_connections(definition, server=binding != "react"),
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


def check_requests(binding: str, mock: MockApi) -> None:
    """Check the requests of the app at the mock server of the API."""
    if binding == "react":
        if mock.recorded():
            raise ConnectionUiTestError(f"{binding}: the app with mock data called the server.")
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


def nextjs_test(definition: AppDefinition, out: Path) -> None:
    binding, app = "nextjs", out / "nextjs"
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app)
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
            check_ui(binding, definition)
        check_requests(binding, mock)


def react_test(definition: AppDefinition, out: Path) -> None:
    binding, app = "react", out / "react"
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app)
    port = str(PORTS[binding])
    command = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    with MockApi(definition, port=MOCK_PORT) as mock:
        with started(binding, command, app, {**os.environ, "PORT": port}):
            wait_for(binding, f"http://localhost:{port}/sign-in")
            check_ui(binding, definition)
        check_requests(binding, mock)


def react_api_test(definition: AppDefinition, out: Path) -> None:
    """The React app with the FastAPI app: the page uses the routes of the FastAPI app."""
    binding = "react-api"
    marker = "\napp:\n"
    text = DEFINITION.read_text()
    if marker not in text:
        raise ConnectionUiTestError(f"{DEFINITION} has no 'app:' line.")
    text = text.replace(marker, f"{marker}  {DATA_KEY}: api\n", 1)
    # The copy is in another folder: the paths of the OpenAPI documents become absolute.
    folder = DEFINITION.parent.resolve()
    for name, api in definition.apis.items():
        old = f"document: {api.document}"
        if old not in text:
            raise ConnectionUiTestError(f"{DEFINITION}: the API {name} has no line '{old}'.")
        text = text.replace(old, f"document: {folder / api.document}")
    source = out / "react-api.yaml"
    source.write_text(text)
    api, web = out / "react-api-fastapi", out / binding
    generate(source, "fastapi", api)
    generate(source, "react", web)
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
            check_ui(binding, definition)
        check_requests(binding, mock)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("bindings", nargs="*", metavar="binding", help=", ".join(BINDINGS))
    parser.add_argument(
        "--out", type=Path, help="The folder of the apps; the default is a new one."
    )
    args = parser.parse_args()
    bindings: list[str] = args.bindings or list(BINDINGS)
    unknown = [b for b in bindings if b not in BINDINGS]
    if unknown:
        parser.error(f"unknown binding: {', '.join(unknown)}")
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-connection-ui.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    out.mkdir(parents=True, exist_ok=True)
    definition = load_definition(DEFINITION)
    tests = {"react": react_test, "nextjs": nextjs_test, "react-api": react_api_test}
    try:
        for binding in bindings:
            tests[binding](definition, out)
            log(binding, "passed")
    except (ConnectionUiTestError, subprocess.CalledProcessError) as error:
        print(f"connection-ui-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
