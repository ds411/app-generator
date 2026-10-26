"""Start a generated front end, and move a row and a card of the views with a manual order.

The test runs in the apps of tests/fixtures/invoices.yaml (ADR 0039). It
starts the front end with `pnpm dev`:

- `nextjs`: the Next.js app in `--app`, with PGlite (the migrations of
  `pnpm db:generate`, and the seed).
- `react`: the React app in `--app`, with its mock data.
- `react-api`: the test generates the fixture with `x-react-data: api`,
  with the FastAPI binding and the React binding, and starts the FastAPI
  app with SQLite (the migrations, and the seed) and the React app with
  its API client.

Then it runs the UI test ui-tests/tests/order.spec.ts: a row of the
steps table moves by drag and drop and with the arrow keys until the rows
get new values, and a card of the steps board moves to another column.
In the Next.js app and with the API, the test reloads the pages and
checks that the order stays. The mock data of the React app does not
keep a change.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/order_ui_test.py --app <folder> [--binding react]
    uv run scripts/order_ui_test.py --binding react-api

scripts/check-nextjs.sh, scripts/check-react.sh, and
scripts/check-react-api.sh run it. It needs uv, pnpm, and the Chromium
of Playwright (see scripts/smoke_test.py), but not Docker.
"""

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_TESTS = ROOT / "ui-tests"
FIXTURE = ROOT / "tests" / "fixtures" / "invoices.yaml"


def log(message: str) -> None:
    print(f"order-ui-test: {message}", flush=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(url: str, output: Path) -> None:
    for _ in range(180):
        try:
            with urllib.request.urlopen(url, timeout=60):
                return
        except urllib.error.URLError, ConnectionError:
            time.sleep(1)
    sys.exit(f"order-ui-test: {url} does not answer:\n{output.read_text()}")


@contextmanager
def started(command: list[str], cwd: Path, env: dict[str, str], output: Path) -> Generator[None]:
    """Run a server, and stop it and its child processes at the end."""
    with output.open("w") as out:
        # A new session, so that the stop also ends the child processes of pnpm and uv.
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )
    try:
        yield
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)


def ui_test(base: str, reload: bool, temp: Path) -> bool:
    """Run ui-tests/tests/order.spec.ts on the app at `base`. Return True if it passes."""
    with (UI_TESTS / ".install.lock").open("w") as lock:
        # Only one check at a time installs the packages of the UI tests.
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(
            ["pnpm", "install", "--silent", "--frozen-lockfile"], cwd=UI_TESTS, check=True
        )
    log("ui-tests/tests/order.spec.ts")
    result = subprocess.run(
        ["pnpm", "exec", "playwright", "test", "tests/order.spec.ts", "--project", "light"],
        cwd=UI_TESTS,
        env={
            **os.environ,
            "APPGEN_BASE_URL": base,
            "APPGEN_ORDER_TEST": "1",
            "APPGEN_ORDER_RELOAD": "1" if reload else "0",
            "APPGEN_UI_OUTPUT": str(temp / "test-results"),
        },
        check=False,
    )
    return result.returncode == 0


def run_front_end(app: Path, binding: str) -> None:
    """Start the Next.js or the React app in `app`, and run the UI test."""
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_")}
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        if binding == "nextjs":
            log("pnpm db:generate")
            subprocess.run(
                ["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True
            )
            env |= {
                "PORT": str(port),
                "DATABASE_URL": f"pglite:{temp / 'pglite'}",
                "DATABASE_MIGRATE": "true",
                "DATABASE_SEED": "true",
            }
            command = ["pnpm", "--silent", "dev"]
            ready = f"http://localhost:{port}/health"
        else:
            command = ["pnpm", "--silent", "dev", "--port", str(port), "--strictPort"]
            ready = f"http://localhost:{port}/"
        output = temp / "dev.log"
        log(f"pnpm dev on port {port} ({binding})")
        with started(command, app, env, output):
            wait_for(ready, output)
            passed = ui_test(f"http://localhost:{port}", binding == "nextjs", temp)
        if not passed:
            sys.exit(
                f"order-ui-test: the UI test failed. The log of the app:\n{output.read_text()}"
            )


def run_with_api() -> None:
    """Generate the fixture with the API client, start the FastAPI app and the React app, and
    run the UI test."""
    api_port, web_port = free_port(), free_port()
    web_url = f"http://localhost:{web_port}"
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        definition = temp / "invoices.yaml"
        text = FIXTURE.read_text(encoding="utf-8")
        definition.write_text(
            text.replace("  title: Invoices\n", "  title: Invoices\n  x-react-data: api\n", 1)
        )
        api, web = temp / "fastapi", temp / "react"
        for binding, out in (("fastapi", api), ("react", web)):
            log(f"generate the {binding} app")
            subprocess.run(
                [
                    "uv",
                    "run",
                    "--locked",
                    "appgen",
                    "generate",
                    str(definition),
                    "-b",
                    binding,
                    "-o",
                    str(out),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_")}
        # The generated FastAPI app has its own virtual environment.
        env.pop("VIRTUAL_ENV", None)
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{temp / 'local.db'}"
        log("FastAPI: uv sync and alembic upgrade head")
        subprocess.run(["uv", "sync", "--quiet"], cwd=api, env=env, check=True)
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=api, env=env, check=True)
        log("React: pnpm install")
        subprocess.run(["pnpm", "install", "--silent"], cwd=web, check=True)
        api_env = env | {"DATABASE_SEED": "true", "CORS_ORIGINS": json.dumps([web_url])}
        uvicorn = ["uv", "run", "uvicorn", "app.main:app", "--port", str(api_port)]
        vite = ["pnpm", "--silent", "dev", "--port", str(web_port), "--strictPort"]
        web_env = {**os.environ, "VITE_API_URL": f"http://localhost:{api_port}"}
        log(f"FastAPI on port {api_port}, React on port {web_port}")
        with (
            started(uvicorn, api, api_env, temp / "fastapi.log"),
            started(vite, web, web_env, temp / "react.log"),
        ):
            wait_for(f"http://localhost:{api_port}/health", temp / "fastapi.log")
            wait_for(f"{web_url}/", temp / "react.log")
            passed = ui_test(web_url, True, temp)
        if not passed:
            sys.exit(
                "order-ui-test: the UI test failed. The log of the FastAPI app:\n"
                + (temp / "fastapi.log").read_text()
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, help="The generated front end (not for react-api).")
    parser.add_argument("--binding", choices=("nextjs", "react", "react-api"), default="nextjs")
    args = parser.parse_args()
    if args.binding == "react-api":
        run_with_api()
    elif args.app is None:
        parser.error("--app is required for nextjs and react")
    else:
        run_front_end(args.app.resolve(), args.binding)
    log(f"passed (a row and a card moved, {args.binding})")


if __name__ == "__main__":
    main()
