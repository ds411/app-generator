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
5. Check the large lists (M26): no page loads all records of an entity.
   A page loads its related records by ID. The owner field of the edit
   form searches the people on the server, with more people than one
   page of options, and saves the person of the search. The board loads
   one page for each column, shows the counts of the server, loads more
   cards of a column, and moves a card. The calendar (a view that the
   test adds to the definition) loads only the records of the shown days.
   The dashboard calls the endpoint of each widget once, and loads no
   list of all records. Each checked stat tile shows the value of its
   endpoint, which is the total of the list endpoint with the same filter.
6. With translations: the API gives an error in the second language of
   `Accept-Language`, and the page in the second language asks the API
   for it (ADR 0010).
7. Open the dashboard: its custom widget (the hand-written code in
   examples/project-tracker/extensions/react/) must show the holidays
   that the browser gets from the mock server of the third-party APIs
   (scripts/mock_api.py) through the generated client. The build sets
   the base URLs of the APIs to the mock server.
8. Upload a screenshot of a task in the edit form: the form sends the
   file to the file endpoint of the FastAPI app, and the detail view
   shows the image from its signed link. Then the form removes it
   (ADR 0027).
9. Change the title of the task with the API, open the tab "History" of
   the task, and restore the old title: the React app reads the change
   log from the FastAPI app (ADR 0040).
10. Call the endpoint of an operation of the exposed APIs
    `exchange_rates` and `finance` (`expose: true`) in the FastAPI app:
    the app must call the mock server with the API key, or with an
    OAuth 2.0 token and the cookie parameter, and give the example
    answer.
11. Run the UI test of the live updates (`ui-tests/tests/live.spec.ts`,
    ADR 0051): a task that a second browser adds, changes, and deletes
    shows at once on the task board of the first browser, through the
    stream of the FastAPI app.

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

import datetime as dt
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

from mock_api import SECRET, MockApi
from smoke_test import expected_ui

from appgen.bindings.react.api_client import DATA_KEY, api_entities, widget_endpoints
from appgen.bindings.shared.views import ViewContext
from appgen.dsl import load_definition

DEFINITION = Path("examples/project-tracker/app.yaml")
EXTENSIONS = DEFINITION.parent / "extensions"
API_PORT = 8420
WEB_PORT = 5420
API_URL = f"http://localhost:{API_PORT}"
WEB_URL = f"http://localhost:{WEB_PORT}"
PAGE_SIZE = 20
"""The page size of the project table (`ui.views.project_table.pagination`)."""
PROJECT_COUNT = PAGE_SIZE + 5
OPTION_COUNT = 20
"""The count of the options of a search of a choice (`OPTION_COUNT` of the HTTP store)."""
PEOPLE_COUNT = OPTION_COUNT + 5
"""The people that the test adds for the owner field: more than one page of options."""
BOARD_PAGE = 20
"""The count of cards that a board column loads first (`PAGE_SIZE` of the board view)."""
TODO_COUNT = BOARD_PAGE + 4
"""The tasks that the test adds to the column "To do": more than one page of the column."""
UI_TESTS = Path("ui-tests")
HOLIDAY_NAME = "Christmas Day"
"""A holiday of the example answers of the holidays API, which the dashboard widget shows."""

# Open a page, and wait until it shows a text. The arguments are the URL
# and the text.
TEXT_CHECK = """
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

# Open the project table, and check the requests to the list endpoint of
# the projects: one for each page, and the search and the sort of the
# view. Then open the first project, and check its tabs. With a second
# language, open the table in it: each request to the API must ask for
# its locale and get it. The argument is a JSON object with the URLs,
# the names of the records, and the second language.
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

    if (test.language) {
      const { storageKey, code, locale } = test.language;
      const other = await browser.newPage();
      const wrong = [];
      let answers = 0;
      const store = ([key, value]) => window.localStorage.setItem(key, value);
      await other.addInitScript(store, [storageKey, code]);
      other.on("response", (response) => {
        // EventSource cannot send the language: the stream of the live updates has no text.
        const stream = response.request().resourceType() === "eventsource";
        if (!response.url().startsWith(test.api) || stream) return;
        answers += 1;
        const asked = response.request().headers()["accept-language"];
        const given = response.headers()["content-language"];
        if (asked !== locale || given !== locale) {
          wrong.push(`${response.url()}: ${asked}, ${given}`);
        }
      });
      await other.goto(`${test.web}/projects`);
      await other.getByText(test.names[0], { exact: true }).first().waitFor({ timeout });
      check(answers > 0, "The page in the second language sent no request to the API.");
      check(wrong.length === 0, `The requests do not ask for ${locale}: ${wrong.join(", ")}`);
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
"""


# Open the pages of the large lists (M26), and check their requests to the
# API: no request loads all records of an entity (a list request with the
# largest page and no filter). The argument is a JSON object with the URLs
# and the records of the test.
LIST_CHECK = """
const { existsSync } = require("node:fs");
const { chromium } = require(require.resolve("@playwright/test", { paths: ["ui-tests"] }));
const timeout = 30000;
const PAGE_KEYS = ["limit", "offset", "sort"];
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
    const gets = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (request.method() === "GET" && url.origin === test.api) gets.push(url);
    });
    const shows = (text, scope = page) =>
      scope.getByText(text, { exact: true }).first().waitFor({ timeout });
    const since = (start, path) => gets.slice(start).filter((url) => url.pathname === path);
    const settle = () => page.waitForLoadState("networkidle");
    const button = (name, scope = page) => scope.getByRole("button", { name, exact: true });
    const noLoadAll = (where) => {
      const all = gets.filter((url) => {
        const keys = [...url.searchParams.keys()];
        return url.searchParams.get("limit") === "200" && keys.every((k) => PAGE_KEYS.includes(k));
      });
      check(all.length === 0, `${where} loaded all records: ${all.join(", ")}`);
    };

    // The table loads the owners of its page by ID.
    await page.goto(`${test.web}/projects`);
    await shows(test.names[0]);
    await settle();
    const owners = since(0, "/people");
    check(owners.length === 1, `The table sent ${owners.length} requests for the owners, not 1.`);
    check(owners[0].searchParams.has("id"), `The request of the owners has no IDs: ${owners[0]}`);
    noLoadAll("The project table");

    // The owner field searches the people on the server.
    await page.goto(`${test.web}/projects/${test.project}`);
    await button("Edit").click();
    let start = gets.length;
    await page.locator("#edit-project-owner").click();
    await page.getByRole("option").nth(test.optionCount - 1).waitFor({ timeout });
    const options = await page.getByRole("option").count();
    check(options === test.optionCount, `The owner field shows ${options} options.`);
    const first = since(start, "/people").map((url) => url.searchParams.get("limit"));
    check(first.includes(String(test.optionCount)), `The owner field asked for ${first}.`);
    start = gets.length;
    await page.getByPlaceholder("Search").fill(test.searched.text);
    await page.getByRole("option", { name: test.searched.name, exact: true }).click();
    const words = since(start, "/people").map((url) => url.searchParams.get("q"));
    check(words.includes(test.searched.text), `The owner field searched for ${words}.`);
    const patch = (response) => response.request().method() === "PATCH";
    const saved = page.waitForResponse(patch, { timeout });
    await button("Save").click();
    await saved;
    const project = await (await fetch(`${test.api}/projects/${test.project}`)).json();
    check(project.owner_id === test.searched.id, `The owner is ${project.owner_id}.`);
    await settle();
    noLoadAll("The project page and its edit form");

    // The board loads one page for each column, with the counts of the server.
    start = gets.length;
    await page.goto(`${test.web}/tasks`);
    const todo = page.getByRole("region", { name: "To do" });
    const progress = page.getByRole("region", { name: "In progress" });
    await shows(String(test.todoCount), todo);
    await settle();
    const columns = since(start, "/tasks");
    check(columns.length === test.columns, `The board sent ${columns.length} requests.`);
    const onePage = (url) =>
      url.searchParams.has("status") && url.searchParams.get("limit") === String(test.boardPage);
    check(columns.every(onePage), `The board requests are not pages: ${columns.join(", ")}`);
    const cards = todo.getByRole("button", { name: "Actions" });
    const shown = await cards.count();
    check(shown === test.boardPage, `The column "To do" shows ${shown} cards.`);
    await button("Show more", todo).click();
    await cards.nth(test.todoCount - 1).waitFor({ timeout });
    check(!(await button("Show more", todo).isVisible()), "The full column has more cards.");
    await cards.first().click();
    await page.getByRole("menuitem", { name: "In progress", exact: true }).click();
    await shows(String(test.todoCount - 1), todo);
    await shows("1 / 8", progress);
    await settle();
    noLoadAll("The board");

    // The calendar loads the records of the shown days.
    start = gets.length;
    await page.goto(`${test.web}${test.calendar}`);
    await shows(test.dueToday);
    await settle();
    const ranges = since(start, "/tasks");
    const range = (url) => test.range.map((name) => url.searchParams.get(name));
    check(ranges.length === 1, `The calendar sent ${ranges.length} requests, not 1.`);
    const [from, to] = range(ranges[0]);
    const shownToday = from && to && from <= test.today && test.today <= to;
    check(shownToday, `The calendar asked for the days ${from} to ${to}.`);
    start = gets.length;
    const tasks = (request) => new URL(request.url()).pathname === "/tasks";
    const loaded = page.waitForRequest(tasks, { timeout });
    await button("Next month").click();
    await loaded;
    const [next] = range(since(start, "/tasks")[0]);
    check(next > from, `The next month asked for the days from ${next}, not after ${from}.`);
    await settle();
    noLoadAll("The calendar");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
"""

# Open the dashboard, and check its requests to the API: one request for
# each widget endpoint, and no request that loads all records of an
# entity. Each stat tile must show the value of its endpoint, and the
# value that the list endpoint gives. The argument is a JSON object with
# the URLs, the stat tiles, and the endpoints of the widgets.
DASHBOARD_CHECK = """
const { existsSync } = require("node:fs");
const { chromium } = require(require.resolve("@playwright/test", { paths: ["ui-tests"] }));
const timeout = 30000;
const PAGE_KEYS = ["limit", "offset", "sort"];
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
    const gets = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (request.method() === "GET" && url.origin === test.api) gets.push(url);
    });
    await page.goto(`${test.web}/`);
    for (const stat of test.stats) {
      const tile = page.locator("[data-slot=card]", {
        has: page.getByText(stat.label, { exact: true }),
      });
      const api = await (await fetch(`${test.api}${stat.path}`)).json();
      check(api.value === stat.expected, `${stat.path} gives ${api.value}, not ${stat.expected}.`);
      const value = tile.locator("p.tabular-nums");
      await value.getByText(String(stat.expected), { exact: true }).waitFor({ timeout });
    }
    await page.waitForLoadState("networkidle");
    for (const path of test.widgets) {
      const calls = gets.filter((url) => url.pathname === path);
      check(calls.length === 1, `The dashboard called ${path} ${calls.length} times, not once.`);
    }
    const dated = gets.filter((url) => test.today.includes(url.pathname));
    check(dated.every((url) => url.searchParams.has("today")), `No date of today: ${dated}`);
    const all = gets.filter((url) => {
      const keys = [...url.searchParams.keys()];
      return url.searchParams.get("limit") === "200" && keys.every((k) => PAGE_KEYS.includes(k));
    });
    check(all.length === 0, `The dashboard loaded all records: ${all.join(", ")}`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
"""

# Open a task, upload a screenshot in the edit form, and check the
# request to the file endpoint, the record, and the image of the detail
# view. Then remove the screenshot. The argument is a JSON object with
# the URLs, the ID of the task, and the image as Base64.
FILE_CHECK = """
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
    const endpoint = `${test.api}/tasks/${test.task}/screenshot`;
    const fileRequest = (method) => (response) =>
      response.url() === endpoint && response.request().method() === method;
    const record = async () => (await fetch(`${test.api}/tasks/${test.task}`)).json();

    await page.goto(`${test.web}/tasks/${test.task}`);
    const image = page.locator("main").getByRole("img", { name: "screenshot.png" });
    await page.getByRole("button", { name: "Edit", exact: true }).first().click();
    const sheet = page.getByRole("dialog");
    const buffer = Buffer.from(test.png, "base64");
    const file = { name: "screenshot.png", mimeType: "image/png", buffer };
    await sheet.locator('input[type="file"]').setInputFiles(file);
    const uploaded = page.waitForResponse(fileRequest("PUT"), { timeout });
    await sheet.getByRole("button", { name: "Save", exact: true }).click();
    const upload = await uploaded;
    check(upload.status() === 200, `The upload gave the status ${upload.status()}.`);
    await sheet.waitFor({ state: "hidden", timeout });
    const stored = (await record()).screenshot;
    const shown = JSON.stringify(stored);
    check(stored && stored.name === "screenshot.png", `The task has the file ${shown}.`);
    check(stored.size === file.buffer.length, `The file has ${stored.size} bytes.`);
    await image.waitFor({ timeout });
    const src = await image.getAttribute("src");
    check(src && src.startsWith(`${test.api}/file-links/`), `The image comes from ${src}.`);
    const loaded = (img) => img.complete && img.naturalWidth === 48;
    await page.waitForFunction(loaded, await image.elementHandle(), { timeout });

    await page.getByRole("button", { name: "Edit", exact: true }).first().click();
    await sheet.getByRole("button", { name: "Remove the file", exact: true }).click();
    const removed = page.waitForResponse(fileRequest("DELETE"), { timeout });
    await sheet.getByRole("button", { name: "Save", exact: true }).click();
    const remove = await removed;
    check(remove.status() === 200, `The delete gave the status ${remove.status()}.`);
    await sheet.waitFor({ state: "hidden", timeout });
    await image.waitFor({ state: "detached", timeout });
    check((await record()).screenshot === null, "The task has a screenshot after the delete.");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
"""
# Open the tab "History" of a task that the API changed, and restore the
# old title (ADR 0040): the React app reads the change log from the
# FastAPI app. The argument is a JSON object with the URLs, the ID of the
# task, and the old and the new title.
HISTORY_CHECK = """
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
    await page.goto(`${test.web}/tasks/${test.task}`);
    await page.getByRole("tab", { name: "History", exact: true }).click({ timeout });
    const entry = page.locator("li[data-action=changed]", { hasText: test.title }).first();
    await entry.waitFor({ timeout });
    const restored = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/restore") &&
        response.request().method() === "POST",
      { timeout },
    );
    await entry.getByRole("button", { name: "Restore", exact: true }).click();
    const response = await restored;
    check(response.status() === 200, `The restore gave the status ${response.status()}.`);
    await page.locator("li[data-action=restored]").first().waitFor({ timeout });
    const record = await (await fetch(`${test.api}/tasks/${test.task}`)).json();
    check(record.title === test.old, `The task has the title ${record.title}, not ${test.old}.`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
"""
SCREENSHOT = (
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAgCAIAAADbtmxLAAAARklEQVR42u3WsQ0AIAgEQJZxMsd2A93BuACWxoJLvvyEq4"
    "BofaUZc6d53Q8gIKByoF+Db30gIKB6IJsaCAjIP+R0AAEVBx0soKK1++CmdgAAAABJRU5ErkJggg=="
)
"""A PNG image of 48 by 32 pixels, as Base64."""

# The calendar view and its page that the test adds to the definition:
# the project tracker has no calendar.
CALENDAR_VIEW = """\
    task_calendar:
      kind: calendar
      entity: Task
      title: Task calendar
      start: due_date
      label: title
"""
CALENDAR_PAGE = """\
  task_calendar:
    path: /calendar
    title: Calendar
    entity: Task
    content: { view: task_calendar }
"""
CALENDAR_PATH = "/calendar"


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


def check_language(definition_path: Path) -> dict[str, str] | None:
    """Check that the API gives an error in the second language of `Accept-Language`.

    Return the storage key of the language in the React app, the second
    language, and its locale, or None without translations.
    """
    definition = load_definition(definition_path)
    translations = definition.translations
    if translations is None:
        return None
    code, language = next(
        (code, language)
        for code, language in translations.languages.items()
        if code != translations.default
    )
    locale = language.locale_tag(code)
    url = f"{API_URL}/people?limit=0"
    call = urllib.request.Request(url, headers={"Accept-Language": locale})
    try:
        urllib.request.urlopen(call, timeout=30).close()
    except urllib.error.HTTPError as error:
        status, headers, problem = error.code, error.headers, json.loads(error.read())
    else:
        raise ApiClientError(f"GET {url} gave no error.")
    expected = language.text.get("The request is not valid.", "The request is not valid.")
    if status != 422 or problem.get("detail") != expected:
        raise ApiClientError(f"GET {url} in {locale} gave {status}: {problem}")
    if headers.get("Content-Language") != locale:
        given = headers.get("Content-Language")
        raise ApiClientError(f"GET {url} in {locale} gave the Content-Language {given}.")
    return {"storageKey": f"{definition.app.name}-language", "code": code, "locale": locale}


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
    """Write the project tracker with the key `x-react-data: api` in its `app` section.

    The copy also has a calendar of the tasks, on the page `/calendar`.
    """
    text = DEFINITION.read_text()
    for line, added in (
        ("app:", f"  {DATA_KEY}: api\n"),
        ("  views:", CALENDAR_VIEW),
        ("pages:", CALENDAR_PAGE),
    ):
        text, count = re.subn(f"(?m)^{line}\n", f"{line}\n{added}", text, count=1)
        if count != 1:
            raise ApiClientError(f"{DEFINITION} has no '{line}' line.")
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
        # The hand-written code of the example: appgen keeps an extension
        # file that exists.
        if (EXTENSIONS / binding).is_dir():
            shutil.copytree(EXTENSIONS / binding, folder, dirs_exist_ok=True)
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
    log("React: pnpm install, typecheck, and lint")
    run("pnpm", "install", "--silent", cwd=web)
    run("pnpm", "--silent", "typecheck", cwd=web)
    run("pnpm", "--silent", "lint", cwd=web)

    uvicorn = ["uv", "run", "uvicorn", "app.main:app", "--port", str(API_PORT)]
    preview = ["pnpm", "exec", "vite", "preview", "--port", str(WEB_PORT), "--strictPort"]
    loaded = load_definition(definition)
    with MockApi(loaded) as mock:
        # The FastAPI app calls the exposed APIs on the mock server, with
        # their credentials.
        api_env = {
            **database,
            "CORS_ORIGINS": json.dumps([WEB_URL]),
            **mock.env(),
            **mock.credentials(),
        }
        # The browser reads the base URLs of the APIs from the build variables.
        apis = {f"VITE_{name}": url for name, url in mock.env().items()}
        log("React: pnpm build with the mock server of the third-party APIs")
        build_env = {"VITE_API_URL": API_URL, **apis}
        run("pnpm", "--silent", "build", cwd=web, env=build_env, quiet=True)
        with (
            started(uvicorn, api, api_env, out / "fastapi.log"),
            started(preview, web, {}, out / "react.log"),
        ):
            check_apps(definition, mock)
    log("passed")


def check_apps(definition: Path, mock: MockApi) -> None:
    """Check the running apps: the API client, and the client of the holidays API."""
    wait_for(f"{API_URL}/health")
    log("check the endpoints of the API client in the OpenAPI document")
    check_openapi(definition)
    log(f"add a person, {PROJECT_COUNT} projects, and a task with the API")
    person = request("POST", f"{API_URL}/people", {"name": "Ada API", "email": "ada@example.com"})
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
    created_task = request("POST", f"{API_URL}/tasks", task)
    log(f"add {PEOPLE_COUNT} people, and {TODO_COUNT} tasks to do, for the large lists")
    people = [
        request(
            "POST",
            f"{API_URL}/people",
            {"name": f"API person {number:02d}", "email": f"person{number}@example.com"},
        )
        for number in range(1, PEOPLE_COUNT + 1)
    ]
    for number in range(1, TODO_COUNT + 1):
        # The tasks of another project: the first page of the tasks tab stays the same.
        todo = {"title": f"API todo {number:02d}", "project_id": projects[2]["id"]}
        request("POST", f"{API_URL}/tasks", todo)
    today = dt.date.today().isoformat()
    due = {"title": "API due today", "project_id": projects[1]["id"], "due_date": today}
    request("POST", f"{API_URL}/tasks", due)
    language = check_language(definition)
    if language is not None:
        log(f"the API gives its messages in '{language['locale']}' for Accept-Language")
    wait_for(WEB_URL)
    log(f"open {WEB_URL}/projects, and check the requests of the pages")
    check: dict[str, object] = {
        "api": API_URL,
        "web": WEB_URL,
        "pageSize": str(PAGE_SIZE),
        "names": names,
        "project": projects[0]["id"],
        "task": task["title"],
        "person": person["name"],
        "language": language,
    }
    run("node", "-e", PAGE_CHECK, json.dumps(check))
    # The board and the calendar get the names of their parameters from the plan of the views.
    loaded = load_definition(definition)
    endpoints = {name: api.list_endpoint for name, api in api_entities(loaded).items()}
    plans = ViewContext(loaded, endpoints=endpoints)
    calendar = plans.view_plan("task_calendar").server
    assert calendar is not None and calendar.range is not None
    searched = people[-1]
    lists: dict[str, object] = {
        "api": API_URL,
        "web": WEB_URL,
        "names": names,
        "project": projects[0]["id"],
        "optionCount": OPTION_COUNT,
        "searched": {
            "id": searched["id"],
            "name": searched["name"],
            "text": f"person {PEOPLE_COUNT}",
        },
        "columns": len(plans.view_plan("task_board").board_columns),
        "boardPage": BOARD_PAGE,
        # The tasks of the column "To do": all tasks of the test have the default status.
        "todoCount": request("GET", f"{API_URL}/tasks?status=todo&limit=1")["total"],
        "calendar": CALENDAR_PATH,
        "range": list(calendar.range),
        "today": today,
        "dueToday": due["title"],
    }
    log(f"open the large lists: no page loads all records ({len(people)} people)")
    run("node", "-e", LIST_CHECK, json.dumps(lists))
    widgets = widget_endpoints(loaded)
    open_tasks = "&".join(f"status={s}" for s in ("todo", "in_progress", "in_review"))
    stats = [
        ("active_projects", "Active projects", "/projects?status=active&limit=1"),
        ("open_tasks", "Open tasks", f"/tasks?{open_tasks}&limit=1"),
    ]
    dashboard: dict[str, object] = {
        "api": API_URL,
        "web": WEB_URL,
        "stats": [
            {
                "label": label,
                "path": widgets[f"ui.dashboards.overview.widgets.{name}"].path,
                "expected": request("GET", f"{API_URL}{query}")["total"],
            }
            for name, label, query in stats
        ],
        "widgets": [w.path for w in widgets.values()],
        "today": [w.path for w in widgets.values() if w.today],
    }
    log(f"open {WEB_URL}/: the dashboard calls each widget endpoint once ({len(widgets)})")
    run("node", "-e", DASHBOARD_CHECK, json.dumps(dashboard))
    log(f"open {WEB_URL}/, and wait for the holiday '{HOLIDAY_NAME}' of the mock server")
    run("node", "-e", TEXT_CHECK, f"{WEB_URL}/", HOLIDAY_NAME)
    calls = mock.calls("holidays", "getNextPublicHolidays")
    if not calls:
        raise ApiClientError("The dashboard did not call the holidays API.")
    log(f"the dashboard called the holidays API {len(calls)} times")
    files = {"api": API_URL, "web": WEB_URL, "task": created_task["id"], "png": SCREENSHOT}
    log(f"open {WEB_URL}/tasks/{created_task['id']}, and upload and remove a screenshot")
    run("node", "-e", FILE_CHECK, json.dumps(files))
    renamed = "API task, renamed"
    request("PATCH", f"{API_URL}/tasks/{created_task['id']}", {"title": renamed})
    history = {
        "api": API_URL,
        "web": WEB_URL,
        "task": created_task["id"],
        "title": renamed,
        "old": task["title"],
    }
    log("change the title of the task with the API, and restore it in its history tab")
    run("node", "-e", HISTORY_CHECK, json.dumps(history))
    check_exposed_api(mock)
    check_live(definition)


def check_live(definition: Path) -> None:
    """Run the UI test of the live updates on the React app and the FastAPI app (ADR 0051)."""
    log("change a task in a second browser: the task board of the first shows each change")
    loaded = load_definition(definition)
    expected_file = (UI_TESTS / "expected" / "react-api.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    # The React app reads the stream of the FastAPI app: it has the live entities.
    live = [name for name, entity in loaded.entities.items() if entity.live]
    expected = {**expected_ui("react", loaded), "live": live}
    expected_file.write_text(json.dumps(expected, indent=2) + "\n")
    env = {
        "APPGEN_BASE_URL": WEB_URL,
        "APPGEN_UI_EXPECTED": str(expected_file),
        "APPGEN_UI_OUTPUT": str((UI_TESTS / "test-results" / "react-api-live").resolve()),
    }
    command = ["pnpm", "exec", "playwright", "test", "tests/live.spec.ts", "--project", "light"]
    run(*command, cwd=UI_TESTS, env=env)


def check_exposed_api(mock: MockApi) -> None:
    """Check that the FastAPI app calls the exposed APIs with their credentials."""
    url = f"{API_URL}/apis/exchange-rates/get-latest-rates?base=EUR&symbols=USD&symbols=GBP"
    log(f"call {url}")
    answer = request("GET", url)
    expected = next(r.example for r in mock.routes if r.operation_id == "getLatestRates")
    if answer != expected:
        raise ApiClientError(f"The endpoint gave {answer}, not the example {expected}.")
    calls = mock.calls("exchange_rates", "getLatestRates")
    if len(calls) != 1:
        raise ApiClientError(f"The FastAPI app called the API {len(calls)} times, not 1.")
    call = cast(dict[str, Any], calls[0])
    if call["query"] != {"base": ["EUR"], "symbols": ["USD", "GBP"]}:
        raise ApiClientError(f"The FastAPI app sent the query {call['query']}.")
    if call["headers"].get("x-api-key") != SECRET:
        raise ApiClientError("The FastAPI app did not send the API key of the API.")
    log("the FastAPI app called the exchange rates API with its API key")

    url = f"{API_URL}/apis/finance/get-budget?project=APP&tenant=acme"
    log(f"call {url}")
    answer = request("GET", url)
    expected = next(r.example for r in mock.routes if r.operation_id == "getBudget")
    if answer != expected:
        raise ApiClientError(f"The endpoint gave {answer}, not the example {expected}.")
    tokens = mock.calls("finance", "token")
    if len(tokens) != 1:
        raise ApiClientError(f"The FastAPI app got {len(tokens)} tokens, not 1.")
    calls = mock.calls("finance", "getBudget")
    if len(calls) != 1:
        raise ApiClientError(f"The FastAPI app called the API {len(calls)} times, not 1.")
    headers = cast(dict[str, Any], calls[0])["headers"]
    if headers.get("authorization") != "Bearer mock-token-1":
        raise ApiClientError("The FastAPI app did not send the token of the token endpoint.")
    if headers.get("cookie") != "tenant=acme":
        raise ApiClientError(f"The FastAPI app sent the cookies {headers.get('cookie')!r}.")
    log("the FastAPI app called the finance API with an OAuth 2.0 token and the cookie")


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
