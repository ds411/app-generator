"""Call the third-party APIs from a generated app, and check the requests on the mock server.

The tests of the generated FastAPI app use a mock transport, and the
other checks of the apps call only JSON operations. This check proves
that the generated clients send forms, files, cookies, and OAuth 2.0
tokens over HTTP, and read text and binary answers, as the OpenAPI
documents of the project tracker describe (ADR 0019).

The script writes a driver in the folder `.appgen-check/` of the app
(and deletes it at the end), starts the mock server of the APIs (scripts/mock_api.py), and runs the
driver with the base URLs and the credentials of the APIs:

- fastapi: a Python driver with the clients of `app/integrations/`
  (`uv run python`).
- nextjs: a TypeScript driver with the server clients of
  `@/shared/api/` (`pnpm exec tsx`, with the condition `react-server`,
  so that the import `server-only` works).
- react: a TypeScript driver in the server of Vite (`ssrLoadModule`),
  with the client of the API `documents` and the mock data of the
  exposed API `finance`.

The driver uploads a file with a multipart form (`uploadAttachment`),
sends a form (`sendFeedback`), reads a text answer (`exportTasks`) and a
binary answer (`downloadReport`), and gets a budget three times at the
same time (`getBudget`, OAuth 2.0 and a cookie parameter). Then it
revokes the tokens on the mock server, and gets the budget again. The
script checks the answers and the recorded requests: the fields and the
files of the forms, the header `Accept`, the header `Cookie`, one token
request for the three requests at the same time, and one new token after
the status 401.

Run it from the repository root, on an app that a check script generated
and installed:

    uv run scripts/api_calls.py <binding> <app folder>
"""

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from mock_api import CLIENT_ID, SECRET, MockApi

from appgen.dsl import load_definition
from appgen.dsl.openapi import EXAMPLE_TEXT

DEFINITION = Path("examples/project-tracker/app.yaml")
BINDINGS = ("fastapi", "nextjs", "react")
FILE = {"filename": "notes.txt", "type": "text/plain", "content": "Notes of the plan"}
TENANT = "acme corp"
"""The value of the cookie parameter `tenant`: the client percent-encodes the space."""

PY_DRIVER = """\
import asyncio
import json
import os
import urllib.request

from app.integrations.documents.client import DocumentsClient
from app.integrations.documents.models import SendFeedbackBody, UploadAttachmentBody
from app.integrations.finance.client import FinanceClient
from app.integrations.http import ApiFile

FILE = json.loads(os.environ["APPGEN_FILE"])
TENANT = os.environ["APPGEN_TENANT"]


async def main() -> None:
    env = os.environ
    async with DocumentsClient(env["DOCUMENTS_API_URL"]) as documents:
        file = ApiFile(FILE["filename"], FILE["content"].encode(), FILE["type"])
        body = UploadAttachmentBody(file=file, project="APP", tags=["plan", "notes"])
        upload = await documents.upload_attachment(body)
        await documents.send_feedback(SendFeedbackBody(message="Good app & fast", rating=5))
        exported = await documents.export_tasks("APP")
        report = await documents.download_report("APP")
    finance = FinanceClient(
        env["FINANCE_API_URL"], env["FINANCE_CLIENT_ID"], env["FINANCE_CLIENT_SECRET"]
    )
    async with finance:
        calls = [finance.get_budget("APP", TENANT) for _ in range(3)]
        budgets = list(await asyncio.gather(*calls))
        revoke = urllib.request.Request(env["APPGEN_MOCK_URL"] + "/_revoke", method="POST")
        urllib.request.urlopen(revoke).close()
        budgets.append(await finance.get_budget("APP", TENANT))
    answer = {
        "upload": upload.model_dump(mode="json", by_alias=True),
        "export": exported,
        "report": report.decode(),
        "budgets": [budget.model_dump(mode="json", by_alias=True) for budget in budgets],
    }
    print(json.dumps(answer))


asyncio.run(main())
"""

TS_DRIVER = """\
import { %(documents)s } from "@/shared/api/documents";
import { financeClient } from "@/shared/api/finance";

const file = JSON.parse(process.env.APPGEN_FILE ?? "{}");
const tenant = process.env.APPGEN_TENANT ?? "";

export async function main(): Promise<void> {
  const documents = %(client)s;
  const upload = await documents.uploadAttachment({
    file: new File([file.content], file.filename, { type: file.type }),
    project: "APP",
    tags: ["plan", "notes"],
  });
  await documents.sendFeedback({ message: "Good app & fast", rating: 5 });
  const exported = await documents.exportTasks({ project: "APP" });
  const report = await documents.downloadReport({ project: "APP" });
  const finance = financeClient();
  const budget = () => finance.getBudget({ project: "APP", tenant });
  const budgets = await Promise.all([budget(), budget(), budget()]);
  const revoked = await fetch(`${process.env.APPGEN_MOCK_URL}/_revoke`, { method: "POST" });
  if (!revoked.ok) throw new Error(`The mock server gave ${revoked.status} for /_revoke.`);
  budgets.push(await budget());
  const answer = { upload, export: exported, report: await report.text(), budgets };
  console.log(JSON.stringify(answer));
}
%(run)s"""

# Load the driver in the server of Vite, which resolves `@/` and gives
# `import.meta.env`, as in the app.
VITE_RUN = """\
import { createServer } from "vite";

const server = await createServer({
  server: { middlewareMode: true, hmr: false, watch: null },
  appType: "custom",
  logLevel: "error",
});
try {
  const { main } = await server.ssrLoadModule("/.appgen-check/driver.ts");
  await main();
} finally {
  await server.close();
}
"""


class ApiCallsError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"api-calls: {binding}: {message}", flush=True)


def write_driver(binding: str, app: Path) -> list[str]:
    """Write the driver in the app, and return the command that runs it."""
    folder = app / ".appgen-check"
    folder.mkdir(exist_ok=True)
    if binding == "fastapi":
        (folder / "driver.py").write_text(PY_DRIVER)
        return ["uv", "run", "--quiet", "python", ".appgen-check/driver.py"]
    if binding == "nextjs":
        driver = TS_DRIVER % {
            "documents": "documentsClient",
            "client": "documentsClient()",
            "run": "\nmain().catch((error: unknown) => {\n"
            "  console.error(error);\n  process.exit(1);\n});\n",
        }
        (folder / "driver.ts").write_text(driver)
        return ["pnpm", "exec", "tsx", "--conditions=react-server", ".appgen-check/driver.ts"]
    # The React app: the browser client of the API `documents` with the
    # mock server, not with its mock data.
    driver = TS_DRIVER % {
        "documents": "DocumentsClient",
        "client": "new DocumentsClient({ baseUrl: process.env.DOCUMENTS_API_URL })",
        "run": "",
    }
    (folder / "driver.ts").write_text(driver)
    (folder / "run.mjs").write_text(VITE_RUN)
    return ["node", ".appgen-check/run.mjs"]


def run_driver(binding: str, app: Path, mock: MockApi) -> dict[str, Any]:
    """Run the driver, and return its answer."""
    command = write_driver(binding, app)
    env = {
        **os.environ,
        **mock.env(),
        **mock.credentials(),
        "APPGEN_MOCK_URL": f"http://localhost:{mock.port}",
        "APPGEN_FILE": json.dumps(FILE),
        "APPGEN_TENANT": TENANT,
        "PYTHONPATH": str(app),
    }
    # The generated FastAPI app has its own virtual environment.
    env.pop("VIRTUAL_ENV", None)
    log(binding, "run " + " ".join(command))
    result = subprocess.run(command, cwd=app, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise ApiCallsError(f"the driver failed:\n{result.stdout}{result.stderr}")
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise ApiCallsError(f"the driver gave no answer:\n{result.stderr}")
    return cast(dict[str, Any], json.loads(lines[-1]))


def example(mock: MockApi, operation_id: str) -> object:
    return next(r.example for r in mock.routes if r.operation_id == operation_id)


def only_call(mock: MockApi, api: str, operation_id: str) -> dict[str, Any]:
    calls = mock.calls(api, operation_id)
    if len(calls) != 1:
        raise ApiCallsError(f"the app called {operation_id} {len(calls)} times, not 1.")
    return cast(dict[str, Any], calls[0])


def expect(actual: object, expected: object, what: str) -> None:
    if actual != expected:
        raise ApiCallsError(f"{what} is {actual!r}, not {expected!r}.")


def check_documents(binding: str, mock: MockApi, answer: dict[str, Any]) -> None:
    """Check the forms, the files, and the text and binary answers of the API `documents`."""
    upload = only_call(mock, "documents", "uploadAttachment")
    expect(upload["headers"]["content-type"].split(";")[0], "multipart/form-data", "the body")
    expect(upload.get("files"), {"file": [FILE]}, "the files of the multipart form")
    expect(upload.get("form"), {"project": ["APP"], "tags": ["plan", "notes"]}, "the fields")
    expect(answer["upload"], example(mock, "uploadAttachment"), "the answer of uploadAttachment")
    log(binding, "uploadAttachment sends a file and the fields in a multipart form")

    feedback = only_call(mock, "documents", "sendFeedback")
    media = feedback["headers"]["content-type"].split(";")[0]
    expect(media, "application/x-www-form-urlencoded", "the body of sendFeedback")
    form = {"message": ["Good app & fast"], "rating": ["5"]}
    expect(feedback.get("form"), form, "the form of sendFeedback")
    log(binding, "sendFeedback sends a form")

    export = only_call(mock, "documents", "exportTasks")
    expect(export["headers"].get("accept"), "text/csv", "the header Accept of exportTasks")
    expect(export["query"], {"project": ["APP"]}, "the query of exportTasks")
    expect(answer["export"], example(mock, "exportTasks"), "the text of exportTasks")
    log(binding, "exportTasks reads the text answer (Accept: text/csv)")

    report = only_call(mock, "documents", "downloadReport")
    expect(report["headers"].get("accept"), "application/pdf", "the header Accept")
    expect(report["path"], "/reports/APP", "the path of downloadReport")
    expect(answer["report"], EXAMPLE_TEXT, "the content of downloadReport")
    log(binding, "downloadReport reads the binary answer (Accept: application/pdf)")


def check_finance(binding: str, mock: MockApi, answer: dict[str, Any]) -> None:
    """Check the tokens of OAuth 2.0 and the cookie parameter of the API `finance`."""
    budget = example(mock, "getBudget")
    expect(answer["budgets"], [budget] * 4, "the answers of getBudget")
    if binding == "react":
        # The React app gets the exposed API from the FastAPI app, and has
        # its mock data without the FastAPI app.
        expect(mock.calls("finance", "getBudget"), [], "the calls of the mock data")
        log(binding, "the client of the exposed API finance gives its mock data")
        return
    tokens = cast(list[dict[str, Any]], mock.calls("finance", "token"))
    expect(len(tokens), 2, "the number of token requests")
    basic = "Basic " + base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
    grant = {"grant_type": ["client_credentials"], "scope": ["budgets:read"]}
    for token in tokens:
        expect(token["path"], "/oauth/token", "the path of the token request")
        expect(token["headers"].get("authorization"), basic, "the client authentication")
        expect(token.get("form"), grant, "the form of the token request")
    calls = cast(list[dict[str, Any]], mock.calls("finance", "getBudget"))
    authorizations = sorted(c["headers"].get("authorization") for c in calls)
    expected = ["Bearer mock-token-1"] * 4 + ["Bearer mock-token-2"]
    expect(authorizations, expected, "the tokens of the getBudget requests")
    cookies = {c["headers"].get("cookie") for c in calls}
    expect(cookies, {"tenant=acme%20corp"}, "the header Cookie of getBudget")
    log(binding, "getBudget gets one token for three requests at the same time")
    log(binding, "getBudget gets a new token one time after the status 401")
    log(binding, "getBudget sends the cookie parameter in the header Cookie")


def api_calls(binding: str, app: Path) -> None:
    definition = load_definition(DEFINITION)
    try:
        with MockApi(definition) as mock:
            answer = run_driver(binding, app, mock)
            check_documents(binding, mock, answer)
            check_finance(binding, mock, answer)
    finally:
        # The trace check of the app must not see the driver.
        shutil.rmtree(app / ".appgen-check", ignore_errors=True)
    log(binding, "passed")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in BINDINGS:
        print(f"usage: api_calls.py {{{','.join(BINDINGS)}}} <app folder>", file=sys.stderr)
        return 2
    binding, app = sys.argv[1], Path(sys.argv[2]).resolve()
    try:
        api_calls(binding, app)
    except (ApiCallsError, KeyError) as error:
        print(f"api-calls: {binding}: failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
