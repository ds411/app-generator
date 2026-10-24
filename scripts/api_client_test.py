"""Start the FastAPI app and the React app with its API client, and load a page with API data.

The React binding has an API client for the FastAPI app of the same
definition (`x-react-data: api`, see docs/bindings.md). This test proves
that the two generated apps work together:

1. Generate the project tracker with `x-react-data: api`, with the
   FastAPI binding and the React binding.
2. Start the FastAPI app with SQLite (`uv run uvicorn`), and check that
   each endpoint of the API client is in its OpenAPI document.
3. Add a person and a project with the API.
4. Build the React app with `VITE_API_URL`, start it (`pnpm preview`),
   and open the page `/projects` in Chromium: it must show the project.

Run it from the repository root:

    uv run scripts/api_client_test.py [output folder]

The script needs uv, pnpm, and the Playwright package of `ui-tests/`
(`pnpm --dir ui-tests install`). It uses the ports 8420 (FastAPI) and
5420 (React).

Environment variables:
    PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the test, instead of the one
                                  that Playwright installs. Without both, the test
                                  uses /opt/pw-browsers/chromium if it exists.
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for an app to start (default 180).
"""

import json
import os
import re
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
from typing import Any, cast

from appgen.bindings.react.api_client import DATA_KEY, api_entities
from appgen.dsl import load_definition

DEFINITION = Path("examples/project-tracker/app.yaml")
API_PORT = 8420
WEB_PORT = 5420
API_URL = f"http://localhost:{API_PORT}"
WEB_URL = f"http://localhost:{WEB_PORT}"
PROJECT_NAME = "Apollo API test"

# Open a page, and wait until it shows a text. The arguments are the URL
# and the text.
PAGE_CHECK = """
const { existsSync } = require("node:fs");
const { chromium } = require(require.resolve("@playwright/test", { paths: ["ui-tests"] }));
(async () => {
  const [url, text] = process.argv.slice(1);
  const system = "/opt/pw-browsers/chromium";
  let executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;
  if (!executablePath && !existsSync(chromium.executablePath())) {
    executablePath = existsSync(system) ? system : undefined;
  }
  const browser = await chromium.launch({ executablePath });
  try {
    const page = await browser.newPage();
    await page.goto(url);
    await page.getByText(text, { exact: true }).first().waitFor({ timeout: 30000 });
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
"""


class ApiClientError(Exception):
    """A failed check."""


def log(message: str) -> None:
    print(f"api-client-test: {message}", flush=True)


def run(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None, quiet: bool = False
) -> None:
    output = subprocess.DEVNULL if quiet else None
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})}, stdout=output)


def request(method: str, url: str, body: object | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    call = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(call, timeout=30) as response:
            return cast(dict[str, Any], json.loads(response.read() or b"{}"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise ApiClientError(f"{method} {url} gave {error.code}: {detail}") from error


def wait_for(url: str) -> None:
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
    raise ApiClientError(f"{url} did not answer in {timeout:.0f} s ({last}).")


def api_definition(folder: Path) -> Path:
    """Write the project tracker with the key `x-react-data: api` in its `app` section."""
    text = DEFINITION.read_text()
    text, count = re.subn(r"(?m)^app:\n", f"app:\n  {DATA_KEY}: api\n", text, count=1)
    if count != 1:
        raise ApiClientError(f"{DEFINITION} has no 'app:' line.")
    # The other files of the example, for example the OpenAPI documents of its APIs.
    shutil.copytree(DEFINITION.parent, folder, dirs_exist_ok=True)
    path = folder / "app.yaml"
    path.write_text(text)
    return path


@contextmanager
def started(args: list[str], cwd: Path, env: dict[str, str], log_file: Path) -> Generator[None]:
    """Start a server process, and stop it at the end."""
    with log_file.open("w") as output:
        process = subprocess.Popen(
            args, cwd=cwd, env={**os.environ, **env}, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            yield
        except BaseException:
            print(log_file.read_text()[-4000:], file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


def check_openapi(definition_path: Path) -> None:
    """Check that each endpoint of the API client is in the OpenAPI document of the app."""
    document = request("GET", f"{API_URL}/openapi.json")
    paths: dict[str, dict[str, object]] = document["paths"]
    missing = [
        f"{endpoint.method} {endpoint.path} ({endpoint.operation})"
        for entity in api_entities(load_definition(definition_path)).values()
        for endpoint in entity.endpoints
        if endpoint.method.lower() not in paths.get(endpoint.path, {})
    ]
    if missing:
        raise ApiClientError("The OpenAPI document has no " + ", ".join(missing) + ".")


def api_client_test(out: Path) -> None:
    definition = api_definition(out)
    api, web = out / "fastapi", out / "react"
    for binding, folder in (("fastapi", api), ("react", web)):
        log(f"generate {definition} with {binding} in {folder}")
        run(
            "uv",
            "run",
            "--locked",
            "appgen",
            "generate",
            str(definition),
            "-b",
            binding,
            "-o",
            str(folder),
            quiet=True,
        )

    database = {"DATABASE_URL": f"sqlite+aiosqlite:///{api / 'local.db'}"}
    log("FastAPI: uv sync and alembic upgrade head")
    run("uv", "sync", "--quiet", cwd=api)
    run("uv", "run", "alembic", "upgrade", "head", cwd=api, env=database)
    log("React: pnpm install and pnpm build")
    run("pnpm", "install", "--silent", cwd=web)
    run("pnpm", "--silent", "build", cwd=web, env={"VITE_API_URL": API_URL}, quiet=True)

    api_env = {**database, "CORS_ORIGINS": json.dumps([WEB_URL])}
    uvicorn = ["uv", "run", "uvicorn", "app.main:app", "--port", str(API_PORT)]
    preview = ["pnpm", "exec", "vite", "preview", "--port", str(WEB_PORT), "--strictPort"]
    with (
        started(uvicorn, api, api_env, out / "fastapi.log"),
        started(preview, web, {}, out / "react.log"),
    ):
        wait_for(f"{API_URL}/health")
        log("check the endpoints of the API client in the OpenAPI document")
        check_openapi(definition)
        log("add a person and a project with the API")
        person = request(
            "POST", f"{API_URL}/people", {"name": "Ada API", "email": "ada@example.com"}
        )
        request(
            "POST",
            f"{API_URL}/projects",
            {"name": PROJECT_NAME, "key": "APT", "owner_id": person["id"]},
        )
        wait_for(WEB_URL)
        log(f"open {WEB_URL}/projects, and wait for '{PROJECT_NAME}'")
        run("node", "-e", PAGE_CHECK, f"{WEB_URL}/projects", PROJECT_NAME)
    log("passed")


def main() -> int:
    if len(sys.argv) > 1:
        out = Path(sys.argv[1]).resolve()
        out.mkdir(parents=True, exist_ok=True)
        folder = None
    else:
        folder = tempfile.TemporaryDirectory(prefix="appgen-api-client.")
        out = Path(folder.name)
    try:
        api_client_test(out)
    except (ApiClientError, subprocess.CalledProcessError) as error:
        print(f"api-client-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
