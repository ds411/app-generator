"""Show the places of a map view in the front ends, with a local tile server (ADR 0046).

The app is tests/fixtures/places.yaml with its seed records. For each
binding, the test:

1. Starts a tile server on the port 8471: it gives the same small PNG
   for each tile `/{z}/{x}/{y}.png`, so that the maps need no network.
2. Generates the app, installs it, lints it, checks its types, builds
   it with the URL of the tile server (`NEXT_PUBLIC_MAP_TILES`,
   `VITE_MAP_TILES`), and runs the trace check on it (`appgen check`).
   The binding `react-api` is the React app with `x-react-data: api` and
   the FastAPI app of the definition.
3. Starts the app: Next.js with PGlite and the seed records, React with
   `vite preview` and its mock data, and react-api with the FastAPI app
   (SQLite, the seed records) and `vite preview` (the list endpoint gives
   the places in the visible area of the map).
4. Runs the UI test `ui-tests/tests/places.spec.ts`: the map of the page
   /map shows a marker for each place and the tiles of the tile server, a
   move of the map changes the list of the places in it, a near filter
   keeps the places near a point, a place of the list and a marker open
   the place, and the form of a new place takes its point.

Run it from the repository root:

    uv run scripts/places_ui_test.py [binding ...] [--out folder]

Without a binding, the script tests React, Next.js, and react-api. It
needs uv, pnpm, and the Chromium of Playwright (see scripts/smoke_test.py).
It uses the ports 5470 (React), 3470 (Next.js), 5471 and 8470
(react-api), and 8471 (the tile server). It does not need Docker.

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
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from smoke_test import expected_ui

from appgen.bindings.react.api_client import DATA_KEY
from appgen.dsl import AppDefinition, load_definition

DEFINITION = Path("tests/fixtures/places.yaml")
UI_TESTS = Path("ui-tests")
BINDINGS = ("react", "nextjs", "react-api")
PORTS = {"react": 5470, "nextjs": 3470, "react-api": 5471}
API_PORT = 8470
"""The port of the FastAPI app of the binding `react-api`."""
TILE_PORT = 8471
TILES = f"http://127.0.0.1:{TILE_PORT}/{{z}}/{{x}}/{{y}}.png"
"""The tile URL of the apps: the local tile server."""
LISBON = ["Belém Tower", "Eduardo VII Park", "Jerónimos Monastery"]
PLACES = {
    "path": "/map",
    "title": "Map of the places",
    "tiles": f"http://127.0.0.1:{TILE_PORT}/",
    # The list sorts the places by name.
    "all": sorted([*LISBON, "Crystal Palace Gardens", "Serralves Museum"]),
    # A move of the map to the south keeps the places of Lisbon.
    "south": LISBON,
    "near": {"label": "Near", "value": "38.70, -9.21", "names": LISBON},
    "marker": "Belém Tower",
    "form": {"path": "/places/new", "name": "Tile Museum", "lat": "38.7110", "lng": "-9.1400"},
}
"""What the UI test expects of the map of the seed records of the fixture."""


class PlacesUiTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"places-ui-test: {binding}: {message}", flush=True)


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})})


def tile_png() -> bytes:
    """Return a tile of 256 x 256 pixels in one light color, as a PNG."""
    size = 256
    row = b"\x00" + bytes((226, 232, 240)) * size
    data = zlib.compress(row * size)

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", data) + chunk(b"IEND", b"")
    )


class TileServer:
    """A local tile server: the same tile for each path `/{z}/{x}/{y}.png`."""

    def __init__(self) -> None:
        self.requests = 0
        tile = tile_png()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if not re.fullmatch(r"/\d+/-?\d+/-?\d+\.png", self.path):
                    self.send_error(404)
                    return
                server.requests += 1
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(tile)))
                self.end_headers()
                self.wfile.write(tile)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", TILE_PORT), Handler)

    def __enter__(self) -> TileServer:
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_: object) -> None:
        self.http.shutdown()
        self.http.server_close()


def generate(definition: Path, binding: str, app: Path) -> None:
    log(binding, f"generate {definition} in {app}")
    command = ["uv", "run", "--locked", "appgen", "generate", str(definition), "-b", binding]
    subprocess.run([*command, "-o", str(app)], check=True, stdout=subprocess.DEVNULL)


def build(binding: str, definition: Path, app: Path, env: dict[str, str]) -> None:
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
    raise PlacesUiTestError(f"{binding}: {url} did not answer in {timeout:.0f} s ({last}).")


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


def check_ui(binding: str, definition: AppDefinition, tiles: TileServer) -> None:
    """Run the UI test of the map on the app that runs, and check that the map loaded tiles."""
    log(binding, "UI test of the map (Playwright)")
    name = f"{binding}-places"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    expected = {
        **expected_ui("react" if binding == "react-api" else binding, definition),
        "places": PLACES,
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
    before = tiles.requests
    command = ["pnpm", "exec", "playwright", "test", "tests/places.spec.ts"]
    run(*command, "--project", "light", cwd=UI_TESTS, env=env)
    if tiles.requests == before:
        raise PlacesUiTestError(f"{binding}: the map loaded no tile from the tile server.")


def nextjs_test(definition: AppDefinition, out: Path, tiles: TileServer) -> None:
    binding, app = "nextjs", out / "nextjs"
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app, {"NEXT_PUBLIC_MAP_TILES": TILES})
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
        wait_for(binding, f"http://localhost:{port}/map")
        check_ui(binding, definition, tiles)


def react_test(definition: AppDefinition, out: Path, tiles: TileServer) -> None:
    binding, app = "react", out / "react"
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app, {"VITE_MAP_TILES": TILES})
    port = str(PORTS[binding])
    command = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    with started(binding, command, app, {**os.environ, "PORT": port}):
        wait_for(binding, f"http://localhost:{port}/map")
        check_ui(binding, definition, tiles)


def react_api_test(definition: AppDefinition, out: Path, tiles: TileServer) -> None:
    """The React app with the FastAPI app: the map loads the places of its visible area."""
    binding = "react-api"
    marker = "\napp:\n"
    text = DEFINITION.read_text()
    if marker not in text:
        raise PlacesUiTestError(f"{DEFINITION} has no 'app:' line.")
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
    build(binding, source, web, {"VITE_API_URL": api_url, "VITE_MAP_TILES": TILES})
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
        wait_for(binding, f"http://localhost:{port}/map")
        check_ui(binding, definition, tiles)


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
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-places-ui.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    out.mkdir(parents=True, exist_ok=True)
    definition = load_definition(DEFINITION)
    tests = {"react": react_test, "nextjs": nextjs_test, "react-api": react_api_test}
    try:
        with TileServer() as tiles:
            for binding in bindings:
                tests[binding](definition, out, tiles)
                log(binding, "passed")
    except (PlacesUiTestError, subprocess.CalledProcessError) as error:
        print(f"places-ui-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
