"""Show the rows of the queries in the views of the front ends (ADR 0045).

The app is tests/fixtures/listings.yaml with the hand-written queries of
tests/fixtures/listings/extensions/ and the seed records. For each
binding, the test:

1. Generates the app, installs it, lints it, checks its types, builds
   it, and runs the trace check on it (`appgen check`). The binding `react-api` is the
   React app with `x-react-data: api` and the FastAPI app of the
   definition.
2. Starts the app: Next.js with PGlite and the seed records (the server
   actions run the queries), React with `vite preview` and its mock data
   (the browser runs the queries), and react-api with the FastAPI app
   (SQLite, the seed records) and `vite preview` (the endpoints of the
   FastAPI app run the queries).
3. Runs the UI test `ui-tests/tests/listings.spec.ts`: the table of the
   page /stays pages the listings of its filters, the card list of the
   page /booking-months/{year} shows the months of the year of its path,
   and the calendar of the page /listings/{id}/calendar shows the
   bookings of one listing.

Run it from the repository root:

    uv run scripts/listings_ui_test.py [binding ...] [--out folder]

Without a binding, the script tests React, Next.js, and react-api. It
needs uv, pnpm, and the Chromium of Playwright (see scripts/smoke_test.py).
It uses the ports 5460 (React), 3460 (Next.js), and 5461 and 8460
(react-api). It does not need Docker.

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

from smoke_test import expected_ui

from appgen.bindings.react.api_client import DATA_KEY
from appgen.dsl import AppDefinition, load_definition

DEFINITION = Path("tests/fixtures/listings.yaml")
EXTENSIONS = Path("tests/fixtures/listings/extensions")
UI_TESTS = Path("ui-tests")
BINDINGS = ("react", "nextjs", "react-api")
PORTS = {"react": 5460, "nextjs": 3460, "react-api": 5461}
API_PORT = 8460
"""The port of the FastAPI app of the binding `react-api`."""
QUERY_VIEWS = {
    "table": {
        "path": "/stays",
        "pages": [["Harbour loft", "Old town flat"], ["River house"]],
        "total": 3,
        "filter": {"label": "Guests", "value": "3", "titles": ["Old town flat", "River house"]},
        "none": {"value": "7", "title": "No stays"},
        "required": {"label": "City", "value": "Amsterdam", "titles": ["Canal room"]},
        "missing": "Enter the required values",
    },
    "cards": {
        "path": "/booking-months/2026",
        "cards": [{"Bookings": "2", "Nights": "6"}, {"Bookings": "1", "Nights": "7"}],
        "emptyPath": "/booking-months/2030",
        "empty": "No bookings in this year",
    },
    "calendar": {
        "record": "Harbour loft",
        "suffix": "/calendar",
        "today": "2026-03-15T12:00:00Z",
        "events": ["Ana"],
        "others": ["Ben", "Chloe"],
    },
}
"""What the UI test expects of the views of the seed records of the fixture."""


class ListingsUiTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"listings-ui-test: {binding}: {message}", flush=True)


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})})


def generate(definition: Path, binding: str, app: Path) -> None:
    """Generate an app with the hand-written queries of the fixture: appgen keeps the files."""
    log(binding, f"generate {definition} in {app}")
    app.mkdir(parents=True, exist_ok=True)
    extensions = EXTENSIONS / binding
    if extensions.is_dir():
        shutil.copytree(extensions, app, dirs_exist_ok=True)
    command = ["uv", "run", "--locked", "appgen", "generate", str(definition), "-b", binding]
    subprocess.run([*command, "-o", str(app)], check=True, stdout=subprocess.DEVNULL)


def build(binding: str, definition: Path, app: Path, env: dict[str, str] | None = None) -> None:
    """Install, lint, type check, and build a front end, and run the trace check on it.

    The build of the Next.js app checks the types. The build of a React app
    does not, so the script runs `pnpm typecheck` in it.
    """
    log(binding, "pnpm install, pnpm lint, pnpm build, and appgen check")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "lint", cwd=app)
    if binding != "nextjs":
        run("pnpm", "--silent", "typecheck", cwd=app)
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
    raise ListingsUiTestError(f"{binding}: {url} did not answer in {timeout:.0f} s ({last}).")


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


def check_ui(binding: str, definition: AppDefinition) -> None:
    """Run the UI test of the views of the queries on the app that runs."""
    log(binding, "UI test of the views of the queries (Playwright)")
    name = f"{binding}-listings"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    expected = {
        **expected_ui("react" if binding == "react-api" else binding, definition),
        "queryViews": QUERY_VIEWS,
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
    command = ["pnpm", "exec", "playwright", "test", "tests/listings.spec.ts"]
    run(*command, "--project", "light", cwd=UI_TESTS, env=env)


def nextjs_test(definition: AppDefinition, out: Path) -> None:
    binding, app = "nextjs", out / "nextjs"
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app)
    run("pnpm", "--silent", "db:generate", cwd=app)
    port = str(PORTS[binding])
    env = {
        **os.environ,
        "PORT": port,
        "DATABASE_URL": f"pglite:{app / '.pglite'}",
        "DATABASE_MIGRATE": "true",
        "DATABASE_SEED": "true",
        "PUBLIC_URL": f"http://localhost:{port}",
    }
    with started(binding, ["pnpm", "--silent", "start"], app, env):
        wait_for(binding, f"http://localhost:{port}/stays")
        check_ui(binding, definition)


def react_test(definition: AppDefinition, out: Path) -> None:
    binding, app = "react", out / "react"
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app)
    port = str(PORTS[binding])
    command = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    with started(binding, command, app, {**os.environ, "PORT": port}):
        wait_for(binding, f"http://localhost:{port}/stays")
        check_ui(binding, definition)


def react_api_test(definition: AppDefinition, out: Path) -> None:
    """The React app with the FastAPI app: the views call the endpoints of the queries."""
    binding = "react-api"
    marker = "\napp:\n"
    text = DEFINITION.read_text()
    if marker not in text:
        raise ListingsUiTestError(f"{DEFINITION} has no 'app:' line.")
    source = out / "react-api.yaml"
    source.write_text(text.replace(marker, f"{marker}  {DATA_KEY}: api\n", 1))
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
    env |= {
        "DATABASE_URL": f"sqlite+aiosqlite:///{api / 'local.db'}",
        "DATABASE_SEED": "true",
        "CORS_ORIGINS": json.dumps([f"http://localhost:{port}"]),
        "PUBLIC_URL": api_url,
        "LOG_JSON": "false",
    }
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=api, env=env, check=True)
    fastapi = ["uv", "run", "fastapi", "run", "app/main.py", "--port", str(API_PORT)]
    preview = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    with (
        started("the FastAPI app", fastapi, api, env),
        started(binding, preview, web, {**os.environ, "PORT": port}),
    ):
        wait_for(binding, f"{api_url}/health")
        wait_for(binding, f"http://localhost:{port}/stays")
        check_ui(binding, definition)


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
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-listings-ui.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    out.mkdir(parents=True, exist_ok=True)
    definition = load_definition(DEFINITION)
    tests = {"react": react_test, "nextjs": nextjs_test, "react-api": react_api_test}
    try:
        for binding in bindings:
            tests[binding](definition, out)
            log(binding, "passed")
    except (ListingsUiTestError, subprocess.CalledProcessError) as error:
        print(f"listings-ui-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
