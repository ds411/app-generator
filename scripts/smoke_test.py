"""Start the generated apps in Docker, and check that they serve pages and data.

The smoke test proves that the apps start, not only that they build. For
each binding, it generates the project tracker, builds the Docker image,
and starts the app: the Next.js app and the FastAPI app with Postgres
(Docker Compose), and the React app with nginx. The Next.js app adds its
seed records when it starts (`DATABASE_SEED=true`), so its pages show
data, as the pages of the React app with its mock data do. Then it
checks the app:

- Next.js and React: open one page for each entity that has a page.
  Next.js: a detail page with an unknown ID gives the status 404.
- FastAPI: call the health check, and the list endpoint of each entity.

With `--local`, the script runs the Next.js app or the FastAPI app on the
machine, without Docker and without a Postgres server: the Next.js app
with PGlite (`pnpm start`), and the FastAPI app with SQLite (`uv run
fastapi run`). The app must be installed, and the Next.js app must be
built (`pnpm build`). Then the script does the same checks. The
third-party APIs of the app point to a mock server
(`scripts/mock_api.py`), and the FastAPI check also runs the custom
operation `schedule_task`, which calls the holidays API through it.
The operation needs the hand-written code of the example
(`examples/project-tracker/extensions/`), which the script copies into
an app that it generates.

With `--ui`, the script also runs the Playwright UI tests in `ui-tests/`
on a front-end app, while the app runs: each page in the light and the
dark mode, the design tokens, and the list and detail pages with records. The screenshots go to
`ui-tests/screenshots/` (git ignores it). Install the browser once with
`pnpm --dir ui-tests install && pnpm --dir ui-tests exec playwright
install chromium`.

Run it from the repository root:

    uv run scripts/smoke_test.py [binding ...]

Without a binding, the script tests all three apps. To test an app that
a check script generated and built, give its folder and its image:

    uv run scripts/smoke_test.py nextjs --app <folder> --image <tag> [--ui]
    uv run scripts/smoke_test.py nextjs --app <folder> --local

The script needs Docker, except with `--local`. It uses the ports 3000 (Next.js), 8000
(FastAPI), and 8080 (React) of the host, one app at a time.

Environment variables:
    POSTGRES_IMAGE                The Postgres image of the Compose files.
    NODE_IMAGE, NGINX_IMAGE       Build arguments of the front-end images.
    UV_IMAGE, PYTHON_IMAGE        Build arguments of the FastAPI image.
    APPGEN_DOCKER_BUILD_ARGS      More arguments for `docker build`.
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for an app to start (default 180).
    APPGEN_UPDATE_SCREENSHOTS     1: write the approved screenshots of the UI tests
                                  again (ui-tests/approved/).
    PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the UI tests, instead of the one
                                  that Playwright installs. Without both, the tests
                                  use /opt/pw-browsers/chromium if it exists.
"""

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import signal
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

from mock_api import MockApi

from appgen.bindings.shared.theme import css_value, css_var
from appgen.dsl import AppDefinition, load_definition
from appgen.gen.tokens import resolve_tokens

DEFINITION = Path("examples/project-tracker/app.yaml")
EXTENSIONS = DEFINITION.parent / "extensions"
UI_TESTS = Path("ui-tests")
BINDINGS = ("nextjs", "fastapi", "react")
BUILD_ARGS = {
    "nextjs": ("NODE_IMAGE",),
    "react": ("NODE_IMAGE", "NGINX_IMAGE"),
    "fastapi": ("UV_IMAGE", "PYTHON_IMAGE"),
}
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
PORTS = {"nextjs": 3000, "fastapi": 8000, "react": 8080}
# The Compose services that run the image of the app.
SERVICES = {"nextjs": ("app",), "fastapi": ("migrate", "api")}


class SmokeError(Exception):
    """A check of the smoke test failed."""


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: str


def log(binding: str, message: str) -> None:
    print(f"smoke-test: {binding}: {message}", flush=True)


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def get(url: str) -> Response:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return Response(response.status, response.read().decode())
    except urllib.error.HTTPError as error:
        return Response(error.code, error.read().decode(errors="replace"))


def post(binding: str, url: str, body: object) -> dict[str, object]:
    """Send a JSON body, and return the JSON answer. A status that is not 2xx is an error."""
    data = json.dumps(body).encode()
    call = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(call, timeout=30) as response:
            return cast(dict[str, object], json.loads(response.read()))
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SmokeError(f"{binding}: POST {url} gave the status {error.code}: {detail}") from None


def wait_for(binding: str, url: str) -> None:
    """Wait until a URL answers with 200."""
    timeout = float(os.environ.get("APPGEN_SMOKE_TIMEOUT", "180"))
    deadline = time.monotonic() + timeout
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            response = get(url)
            if response.status == 200:
                return
            last = f"status {response.status}"
        except OSError as error:
            last = str(error)
        time.sleep(1)
    raise SmokeError(f"{binding}: {url} did not answer in {timeout:.0f} s ({last}).")


def generate(binding: str, out: Path) -> None:
    log(binding, f"generate {DEFINITION} in {out}")
    # The hand-written code of the example: appgen keeps an extension file
    # that exists.
    if (EXTENSIONS / binding).is_dir():
        shutil.copytree(EXTENSIONS / binding, out, dirs_exist_ok=True)
    args = ["uv", "run", "--locked", "appgen", "generate", str(DEFINITION), "-b", binding]
    subprocess.run([*args, "-o", str(out)], check=True, stdout=subprocess.DEVNULL)


def build(binding: str, app: Path, image: str) -> None:
    log(binding, f"docker build -t {image}")
    args = ["docker", "build", "--quiet", "-t", image]
    for name in BUILD_ARGS[binding]:
        if os.environ.get(name):
            args += ["--build-arg", f"{name}={os.environ[name]}"]
    args += shlex.split(os.environ.get("APPGEN_DOCKER_BUILD_ARGS", ""))
    subprocess.run([*args, "."], cwd=app, check=True, stdout=subprocess.DEVNULL)


@contextmanager
def started(binding: str, app: Path, image: str, temp: Path) -> Generator[None]:
    """Start the app, and stop it and delete its data at the end."""
    project = f"appgen-smoke-{binding}"
    if binding == "react":
        log(binding, "docker run")
        run("docker", "run", "-d", "--rm", "--name", project, "-p", "8080:8080", image)
        stop = ["docker", "rm", "-f", project]
        logs = ["docker", "logs", project]
    else:
        # Run the image that the script built, not a new build of Compose.
        override = temp / "smoke.compose.yaml"
        override.write_text(
            "services:\n" + "".join(f"  {s}:\n    image: {image}\n" for s in SERVICES[binding])
        )
        compose = [
            "docker",
            "compose",
            "--progress",
            "quiet",
            "-p",
            project,
            "-f",
            "compose.yaml",
            "-f",
            str(override),
        ]
        log(binding, "docker compose up")
        subprocess.run([*compose, "up", "-d", "--no-build", "--quiet-pull"], cwd=app, check=True)
        stop = [*compose, "down", "-v", "--remove-orphans"]
        logs = [*compose, "logs", "--no-color"]
    try:
        yield
    except SmokeError:
        subprocess.run(logs, cwd=app, check=False)
        raise
    finally:
        log(binding, "stop")
        subprocess.run(stop, cwd=app, check=False, stdout=subprocess.DEVNULL)


@contextmanager
def started_local(binding: str, app: Path, temp: Path, apis: dict[str, str]) -> Generator[None]:
    """Start the app on the machine with its local database, and stop it at the end.

    `apis` holds the environment variables of the base URLs of the APIs.
    """
    env = {**os.environ, "PORT": str(PORTS[binding]), **apis}
    if binding == "nextjs":
        if not (app / "drizzle").is_dir():
            log(binding, "pnpm db:generate")
            subprocess.run(
                ["pnpm", "--silent", "db:generate"], cwd=app, check=True, stdout=subprocess.DEVNULL
            )
        env |= {
            "DATABASE_URL": f"pglite:{temp / 'pglite'}",
            "DATABASE_MIGRATE": "true",
            "DATABASE_SEED": "true",
        }
        command = ["pnpm", "--silent", "start"]
    else:
        # The generated app has its own virtual environment.
        env.pop("VIRTUAL_ENV", None)
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{temp / 'local.db'}"
        log(binding, "alembic upgrade head")
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=app, env=env, check=True)
        command = ["uv", "run", "fastapi", "run", "app/main.py", "--port", env["PORT"]]
    log(binding, f"{' '.join(command)} with {env['DATABASE_URL']}")
    output = temp / "local.log"
    with output.open("w") as out:
        # A new session, so that the stop also ends the child processes of pnpm and uv.
        process = subprocess.Popen(
            command, cwd=app, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )
    try:
        yield
    except SmokeError:
        print(output.read_text(), flush=True)
        raise
    finally:
        log(binding, "stop")
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)


def entity_pages(definition: AppDefinition) -> dict[str, tuple[str, str]]:
    """Return the path and the title of one page for each entity, without path parameters."""
    pages: dict[str, tuple[str, str]] = {}
    for page in definition.pages.values():
        if page.entity and "{" not in page.path and page.entity not in pages:
            pages[page.entity] = (page.path, page.title)
    return pages


def detail_pages(definition: AppDefinition) -> list[str]:
    """Return the names of the pages that show a detail view of a record."""
    ui = definition.ui
    views = ui.views if ui is not None else {}
    return [
        name
        for name, page in definition.pages.items()
        if page.entity
        and "{" in page.path
        and page.content is not None
        and page.content.view in views
        and views[page.content.view].kind == "detail"
    ]


def check_front_end(binding: str, definition: AppDefinition) -> None:
    base = f"http://localhost:{PORTS[binding]}"
    wait_for(binding, base + "/")
    pages = entity_pages(definition)
    for entity in definition.entities:
        if entity not in pages:
            log(binding, f"entity {entity}: no page")
            continue
        path, title = pages[entity]
        response = get(base + path)
        if response.status != 200:
            raise SmokeError(f"{binding}: GET {path} gave the status {response.status}.")
        # The Next.js server renders the page header. The React app is a
        # single-page app: nginx gives index.html for each path.
        expected = title if binding == "nextjs" else '<div id="root">'
        if expected not in response.body:
            raise SmokeError(f"{binding}: GET {path} does not contain {expected!r}.")
        log(binding, f"entity {entity}: GET {path} is OK")
    if binding != "nextjs":
        # The React app is a single-page app: nginx gives status 200 for each path.
        return
    for name in detail_pages(definition):
        path = definition.pages[name].path
        path = re.sub(r"\{[^}]+\}", UNKNOWN_ID, path)
        response = get(base + path)
        if response.status != 404:
            raise SmokeError(f"{binding}: GET {path} gave the status {response.status}, not 404.")
        log(binding, f"page {name}: GET {path} with an unknown ID gives 404")


def check_api(binding: str, definition: AppDefinition) -> None:
    base = f"http://localhost:{PORTS[binding]}"
    wait_for(binding, base + "/health")
    log(binding, "GET /health is OK")
    openapi = json.loads(get(base + "/openapi.json").body)
    paths = {
        op["operationId"]: path
        for path, methods in openapi["paths"].items()
        for method, op in methods.items()
        if method == "get" and "operationId" in op
    }
    for entity in definition.entities:
        name = next(
            (
                n
                for n, o in definition.operations.items()
                if o.entity == entity and o.kind == "list"
            ),
            None,
        )
        if name is None or name not in paths:
            raise SmokeError(f"{binding}: the entity {entity} has no list endpoint.")
        response = get(base + paths[name])
        if response.status != 200:
            raise SmokeError(f"{binding}: GET {paths[name]} gave the status {response.status}.")
        items: object = json.loads(response.body).get("items")
        if not isinstance(items, list):
            raise SmokeError(f"{binding}: GET {paths[name]} gave no list of items.")
        log(
            binding,
            f"entity {entity}: GET {paths[name]} is OK ({len(cast(list[object], items))} records)",
        )


def check_api_operation(binding: str, mock: MockApi) -> None:
    """Run the custom operation `schedule_task`, which calls the holidays API.

    The operation sets the due date of a task to a number of working days
    from today. Its code gets the public holidays from the mock server.
    """
    base = f"http://localhost:{PORTS[binding]}"
    person = post(binding, base + "/people", {"name": "Ada Smoke", "email": "ada@example.com"})
    project = post(
        binding, base + "/projects", {"name": "Smoke", "key": "SMK", "owner_id": person["id"]}
    )
    task = post(binding, base + "/tasks", {"title": "Smoke task", "project_id": project["id"]})
    path = f"/tasks/{task['id']}/schedule-task"
    result = post(binding, base + path, {"working_days": 5, "country_code": "DE"})
    due = result.get("due_date")
    calls = mock.calls("holidays", "getPublicHolidays")
    if not isinstance(due, str) or not calls:
        raise SmokeError(
            f"{binding}: POST {path} gave the due date {due!r} with {len(calls)} calls "
            "of the holidays API."
        )
    log(binding, f"POST {path} is OK: due {due}, with {len(calls)} calls of the holidays API")


def expected_ui(binding: str, definition: AppDefinition) -> dict[str, object]:
    """Return the values that the UI tests expect: the pages and the design tokens."""
    tokens = resolve_tokens(definition)
    body = next((t for t in tokens if t.path == "typography.body"), None)
    font_sizes = {
        mode: str(cast(dict[str, object], value).get("font_size", "1rem"))
        for mode, value in (
            ("light", body.light if body else {}),
            ("dark", body.dark if body else {}),
        )
    }
    return {
        "binding": binding,
        "pages": [
            {
                "name": name,
                "path": page.path,
                "title": page.title,
                "params": [part[1:-1] for part in page.path.split("/") if part.startswith("{")],
                "detail": name in detail_pages(definition),
                "recordActions": [
                    str(a.label) for a in page.actions.values() if a.label and a.kind == "operation"
                ],
            }
            for name, page in definition.pages.items()
        ],
        "colors": [
            {
                "path": t.path,
                "variable": css_var(t.path).removeprefix("var(").removesuffix(")"),
                "light": css_value(t, t.light),
                "dark": css_value(t, t.dark),
            }
            for t in tokens
            if t.group == "color"
        ],
        "bodyFontSize": font_sizes,
    }


def check_ui(binding: str, definition: AppDefinition) -> None:
    """Run the Playwright UI tests on the app that runs."""
    log(binding, "UI tests (Playwright)")
    # One file and one output folder for each binding, so that the checks
    # of the front ends can run at the same time (the pre-push hook).
    expected_file = (UI_TESTS / "expected" / f"{binding}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    expected = json.dumps(expected_ui(binding, definition), indent=2)
    expected_file.write_text(expected + "\n")
    with (UI_TESTS / ".install.lock").open("w") as lock:
        # Only one check at a time installs the packages of the UI tests.
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(
            ["pnpm", "install", "--silent", "--frozen-lockfile"], cwd=UI_TESTS, check=True
        )
        subprocess.run(["pnpm", "--silent", "typecheck"], cwd=UI_TESTS, check=True)
    env = {
        **os.environ,
        "APPGEN_BASE_URL": f"http://localhost:{PORTS[binding]}",
        "APPGEN_UI_EXPECTED": str(expected_file),
        "APPGEN_UI_OUTPUT": str((UI_TESTS / "test-results" / binding).resolve()),
    }
    command = ["pnpm", "exec", "playwright", "test"]
    if os.environ.get("APPGEN_UPDATE_SCREENSHOTS") == "1":
        command.append("--update-snapshots")
    subprocess.run(command, cwd=UI_TESTS, env=env, check=True)


def check(binding: str, definition: AppDefinition, ui: bool) -> None:
    if binding == "fastapi":
        check_api(binding, definition)
    else:
        check_front_end(binding, definition)
        if ui:
            check_ui(binding, definition)


def smoke_test(binding: str, app: Path | None, image: str | None, ui: bool = False) -> None:
    definition = load_definition(DEFINITION)
    with tempfile.TemporaryDirectory(prefix=f"appgen-smoke-{binding}.") as temp:
        if app is None:
            app = Path(temp) / "app"
            generate(binding, app)
        if image is None:
            image = f"appgen-smoke-{binding}"
            build(binding, app, image)
        with started(binding, app, image, Path(temp)):
            check(binding, definition, ui)
    log(binding, "passed")


def smoke_test_local(binding: str, app: Path, ui: bool = False) -> None:
    definition = load_definition(DEFINITION)
    with (
        tempfile.TemporaryDirectory(prefix=f"appgen-smoke-{binding}.") as temp,
        MockApi(definition) as mock,
        started_local(binding, app, Path(temp), mock.env()),
    ):
        check(binding, definition, ui)
        if binding == "fastapi":
            check_api_operation(binding, mock)
    log(binding, "passed with the local database")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("bindings", nargs="*", metavar="binding", help=", ".join(BINDINGS))
    parser.add_argument("--app", type=Path, help="A generated app; the default is a new one.")
    parser.add_argument("--image", help="The Docker image of the app; the default is a new one.")
    parser.add_argument(
        "--ui", action="store_true", help="Also run the UI tests on the front ends."
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run the app of --app on the machine with its local database, not in Docker.",
    )
    args = parser.parse_args()
    bindings: list[str] = args.bindings or list(BINDINGS)
    unknown = [b for b in bindings if b not in BINDINGS]
    if unknown:
        parser.error(f"unknown binding: {', '.join(unknown)}")
    if (args.app or args.image) and len(bindings) != 1:
        parser.error("--app and --image need one binding.")
    if args.local and (args.app is None or args.image or bindings[0] not in SERVICES):
        parser.error("--local needs --app, and the binding nextjs or fastapi.")
    try:
        for binding in bindings:
            if args.local:
                smoke_test_local(binding, args.app, args.ui)
            else:
                smoke_test(binding, args.app, args.image, args.ui)
    except (SmokeError, subprocess.CalledProcessError) as error:
        print(f"smoke-test: failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
