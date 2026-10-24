"""Start the FastAPI app and the React app with its API client, and load a page with API data.

The React binding has an API client for the FastAPI app of the same
definition (`x-react-data: api`, see docs/bindings.md). This test proves
that the two generated apps work together:

1. Generate the project tracker with `x-react-data: api`, with the
   FastAPI binding and the React binding.
2. Start the FastAPI app with SQLite (`uv run uvicorn`), and check that
   each endpoint of the API client is in its OpenAPI document.
3. Add a person, and more projects than one page of the project table,
   with the API.
4. Type check, lint, and build the React app with `VITE_API_URL`, start
   it (`pnpm preview`), and open the page `/projects` in Chromium. The
   table must load each page with one request to the list endpoint, and
   send its search and its sort to the API. The tabs of a project must
   load the tasks and the members of the project from the API.

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
PAGE_SIZE = 20
"""The page size of the project table (`ui.views.project_table.pagination`)."""
PROJECT_COUNT = PAGE_SIZE + 5

# Open the project table, and check the requests to the list endpoint of
# the projects: one for each page, and the search and the sort of the
# view. Then open the first project, and check its tabs. The argument is
# a JSON object with the URLs and the names of the records.
PAGE_CHECK = """
const { existsSync } = require("node:fs");
const { chromium } = require(require.resolve("@playwright/test", { paths: ["ui-tests"] }));
const timeout = 30000;
function check(ok, message) {
  if (!ok) throw new Error(message);
}
(async () => {
  const test = JSON.parse(process.argv[1]);
  const system = "/opt/pw-browsers/chromium";
  let executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;
  if (!executablePath && !existsSync(chromium.executablePath())) {
    executablePath = existsSync(system) ? system : undefined;
  }
  const browser = await chromium.launch({ executablePath });
  try {
    const page = await browser.newPage();
    const lists = [];
    const failed = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (request.method() === "GET" && url.origin === test.api && url.pathname === "/projects") {
        lists.push(url.searchParams);
      }
    });
    page.on("response", (response) => {
      if (response.url().startsWith(test.api) && response.status() >= 400) {
        failed.push(`${response.status()} ${response.url()}`);
      }
    });
    const shows = (text) => page.getByText(text, { exact: true }).first().waitFor({ timeout });

    await page.goto(`${test.web}/projects`);
    await shows(test.names[0]);
    const first = lists[0];
    check(lists.length === 1, `The first page sent ${lists.length} list requests, not 1.`);
    check(first.get("limit") === test.pageSize, `The limit is ${first.get("limit")}.`);
    check(first.get("offset") === "0", `The offset is ${first.get("offset")}.`);
    check(first.get("sort") === "due_date", `The sort is '${first.get("sort")}', not 'due_date'.`);

    await page.getByRole("button", { name: "Next page" }).click();
    await shows(test.names[Number(test.pageSize)]);
    check(lists.length === 2, `The next page sent ${lists.length - 1} list requests, not 1.`);
    check(lists[1].get("offset") === test.pageSize, `The offset is ${lists[1].get("offset")}.`);

    const last = test.names[test.names.length - 1];
    await page.getByRole("searchbox", { name: "Search projects" }).fill(last);
    await shows("1\\u20131 of 1");
    check(lists.at(-1).get("q") === last, "The search is not in the request.");

    await page.getByRole("button", { name: "Reset", exact: true }).click();
    const byName = (response) => response.url().includes("sort=name%2Cdue_date");
    const sorted = page.waitForResponse(byName, { timeout });
    await page.getByRole("button", { name: "Project", exact: true }).click();
    await sorted;
    await shows(test.names[0]);

    await page.goto(`${test.web}/projects/${test.project}`);
    await page.getByRole("tab", { name: "Tasks" }).click();
    await shows(test.task);
    await page.getByRole("tab", { name: "Members" }).click();
    await shows(test.person);
    check(failed.length === 0, `The API gave errors: ${failed.join(", ")}`);
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
    log("React: pnpm install, typecheck, lint, and build")
    run("pnpm", "install", "--silent", cwd=web)
    run("pnpm", "--silent", "typecheck", cwd=web)
    run("pnpm", "--silent", "lint", cwd=web)
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
        log(f"add a person, {PROJECT_COUNT} projects, and a task with the API")
        person = request(
            "POST", f"{API_URL}/people", {"name": "Ada API", "email": "ada@example.com"}
        )
        names = [f"API project {number:02d}" for number in range(1, PROJECT_COUNT + 1)]
        projects = [
            request(
                "POST",
                f"{API_URL}/projects",
                {
                    "name": name,
                    "key": "AP" + chr(ord("A") + index),
                    "owner_id": person["id"],
                    "due_date": f"2027-01-{index + 1:02d}",
                    "member_ids": [person["id"]] if index == 0 else [],
                },
            )
            for index, name in enumerate(names)
        ]
        task = {"title": "API task", "project_id": projects[0]["id"]}
        request("POST", f"{API_URL}/tasks", task)
        wait_for(WEB_URL)
        log(f"open {WEB_URL}/projects, and check the requests of the pages")
        check = {
            "api": API_URL,
            "web": WEB_URL,
            "pageSize": str(PAGE_SIZE),
            "names": names,
            "project": projects[0]["id"],
            "task": task["title"],
            "person": person["name"],
        }
        run("node", "-e", PAGE_CHECK, json.dumps(check))
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
