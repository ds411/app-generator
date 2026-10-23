"""Start the generated apps in Docker, and check that they serve pages and data.

The smoke test proves that the apps start, not only that they build. For
each binding, it generates the project tracker, builds the Docker image,
and starts the app: the Next.js app and the FastAPI app with Postgres
(Docker Compose), and the React app with nginx. Then it checks the app:

- Next.js and React: open one page for each entity that has a page.
- FastAPI: call the health check, and the list endpoint of each entity.

Run it from the repository root:

    uv run scripts/smoke_test.py [binding ...]

Without a binding, the script tests all three apps. To test an app that
a check script generated and built, give its folder and its image:

    uv run scripts/smoke_test.py nextjs --app <folder> --image <tag>

The script needs Docker. It uses the ports 3000 (Next.js), 8000
(FastAPI), and 8080 (React) of the host, one app at a time.

Environment variables:
    POSTGRES_IMAGE                The Postgres image of the Compose files.
    NODE_IMAGE, NGINX_IMAGE       Build arguments of the front-end images.
    UV_IMAGE, PYTHON_IMAGE        Build arguments of the FastAPI image.
    APPGEN_DOCKER_BUILD_ARGS      More arguments for `docker build`.
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for an app to start (default 180).
"""

import argparse
import json
import os
import shlex
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

from appgen.dsl import AppDefinition, load_definition

DEFINITION = Path("examples/project-tracker/app.yaml")
BINDINGS = ("nextjs", "fastapi", "react")
BUILD_ARGS = {
    "nextjs": ("NODE_IMAGE",),
    "react": ("NODE_IMAGE", "NGINX_IMAGE"),
    "fastapi": ("UV_IMAGE", "PYTHON_IMAGE"),
}
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


def entity_pages(definition: AppDefinition) -> dict[str, tuple[str, str]]:
    """Return the path and the title of one page for each entity, without path parameters."""
    pages: dict[str, tuple[str, str]] = {}
    for page in definition.pages.values():
        if page.entity and "{" not in page.path and page.entity not in pages:
            pages[page.entity] = (page.path, page.title)
    return pages


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


def smoke_test(binding: str, app: Path | None, image: str | None) -> None:
    definition = load_definition(DEFINITION)
    with tempfile.TemporaryDirectory(prefix=f"appgen-smoke-{binding}.") as temp:
        if app is None:
            app = Path(temp) / "app"
            generate(binding, app)
        if image is None:
            image = f"appgen-smoke-{binding}"
            build(binding, app, image)
        with started(binding, app, image, Path(temp)):
            if binding == "fastapi":
                check_api(binding, definition)
            else:
                check_front_end(binding, definition)
    log(binding, "passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("bindings", nargs="*", metavar="binding", help=", ".join(BINDINGS))
    parser.add_argument("--app", type=Path, help="A generated app; the default is a new one.")
    parser.add_argument("--image", help="The Docker image of the app; the default is a new one.")
    args = parser.parse_args()
    bindings: list[str] = args.bindings or list(BINDINGS)
    unknown = [b for b in bindings if b not in BINDINGS]
    if unknown:
        parser.error(f"unknown binding: {', '.join(unknown)}")
    if (args.app or args.image) and len(bindings) != 1:
        parser.error("--app and --image need one binding.")
    try:
        for binding in bindings:
            smoke_test(binding, args.app, args.image)
    except (SmokeError, subprocess.CalledProcessError) as error:
        print(f"smoke-test: failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
