"""The browser clients of the third-party APIs in the React app (ADR 0019)."""

import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from appgen.bindings.shared.integrations import ts_apis
from appgen.cli import app
from appgen.dsl import load_definition, load_definition_text
from appgen.gen import GenerationResult, find_binding, generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"
EXPOSE = (
    "    # The FastAPI app calls the API for the React app, which cannot keep the key.\n"
    "    expose: true\n"
)
"""The lines of the example that expose the API `exchange_rates`."""


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def mock_result() -> GenerationResult:
    return generate(load_definition(EXAMPLE), find_binding("react"))


@pytest.fixture(scope="module")
def unexposed_result() -> GenerationResult:
    """The React app of the example, without `expose` on the API `exchange_rates`."""
    text = EXAMPLE.read_text()
    assert EXPOSE in text
    definition = load_definition_text(text.replace(EXPOSE, ""), str(EXAMPLE))
    return generate(definition, find_binding("react"))


@pytest.fixture(scope="module")
def api_files() -> dict[str, str]:
    text, count = re.subn(r"(?m)^app:\n", "app:\n  x-react-data: api\n", EXAMPLE.read_text())
    assert count == 1
    definition = load_definition_text(text, str(EXAMPLE))
    return _files(generate(definition, find_binding("react")))


def test_the_mock_route_of_an_operation_matches_the_end_of_the_path() -> None:
    api = ts_apis(load_definition(EXAMPLE))["holidays"]
    patterns = {m.operation_id: m.path_pattern for m in api.methods}
    assert patterns == {
        "getPublicHolidays": r"/\/PublicHolidays\/[^/]+\/[^/]+$/",
        "getNextPublicHolidays": r"/\/NextPublicHolidays\/[^/]+$/",
    }
    assert api.browser_env == "VITE_HOLIDAYS_API_URL"


def test_with_mock_data_the_client_gives_the_examples(mock_result: GenerationResult) -> None:
    files = _files(mock_result)
    for name in ("index.ts", "types.ts", "client.ts", "mock.ts"):
        assert f"src/shared/api/holidays/{name}" in files
    http = files["src/shared/api/third-party.ts"]
    assert "server-only" not in http
    assert 'import { MOCK_LATENCY_MS } from "./mock-store";' in http
    assert "export function mockFetch(routes: readonly MockRoute[]): typeof fetch {" in http
    client = files["src/shared/api/holidays/client.ts"]
    assert "server-only" not in client
    assert "secret" not in client
    assert 'import { MOCK_ROUTES } from "./mock";' in client
    assert "    fetch: mockFetch(MOCK_ROUTES),\n" in client
    mock = files["src/shared/api/holidays/mock.ts"]
    assert "  // @trace apis.holidays.operations.getNextPublicHolidays\n" in mock
    assert "    path: /\\/NextPublicHolidays\\/[^/]+$/,\n" in mock
    assert '"name": "Christmas Day",' in mock
    assert "VITE_HOLIDAYS_API_URL" not in files["src/vite-env.d.ts"]
    assert "`src/shared/api/holidays/mock.ts`" in files["README.md"]


def test_an_api_with_a_secret_gets_no_client_but_a_gap_and_a_warning(
    unexposed_result: GenerationResult,
) -> None:
    files = _files(unexposed_result)
    assert not any(p.startswith("src/shared/api/exchange-rates/client.ts") for p in files)
    gap = files["src/shared/api/exchange-rates/client.ext.ts"]
    assert gap.splitlines()[1:4] == [
        "// @trace:gap apis.exchange_rates file",
        "// @trace:gap apis.exchange_rates.operations.getLatestRates file",
        "// @trace:gap apis.exchange_rates.operations.convertAmount file",
    ]
    assert "TODO(appgen)" in gap
    assert "EXCHANGE_RATES" not in files["src/shared/api/third-party.ts"]
    assert len(unexposed_result.warnings) == 1
    warning = unexposed_result.warnings[0]
    assert warning.startswith("The API 'exchange_rates' has a secret (EXCHANGE_RATES_API_KEY)")
    assert "Hint: set 'expose: true' on the API" in warning
    assert "custom operation of the FastAPI app (apis: [exchange_rates])" in warning
    assert "'x-react-data: api'" in warning


def test_with_mock_data_an_exposed_api_gets_a_client_with_the_examples(
    mock_result: GenerationResult,
) -> None:
    files = _files(mock_result)
    assert "src/shared/api/exchange-rates/client.ext.ts" not in files
    client = files["src/shared/api/exchange-rates/client.ts"]
    assert 'this.http.request("GET", "/latest", {' in client
    assert "    fetch: mockFetch(MOCK_ROUTES),\n" in client
    assert "options.secret" not in client
    assert "src/shared/api/exchange-rates/mock.ts" in files
    assert mock_result.warnings == []


def test_with_api_data_an_exposed_api_calls_the_endpoints_of_the_fastapi_app(
    api_files: dict[str, str],
) -> None:
    assert "src/shared/api/exchange-rates/mock.ts" not in api_files
    client = api_files["src/shared/api/exchange-rates/client.ts"]
    assert 'import { API_URL, apiFetch } from "@/shared/api/http";' in client
    assert 'this.http.request("GET", "/apis/exchange-rates/get-latest-rates", {' in client
    assert "      query: { base: params.base, symbols: params.symbols },\n" in client
    assert 'this.http.request("POST", "/apis/exchange-rates/convert-amount", {' in client
    assert "    baseUrl: API_URL,\n    fetch: apiFetch,\n" in client
    assert "options.secret" not in client
    http = api_files["src/shared/api/http.ts"]
    assert "export const apiFetch: typeof fetch = (input, init) => {" in http
    assert 'headers.set("Authorization", `Bearer ${token}`);' in http
    assert "EXCHANGE_RATES" not in api_files["src/vite-env.d.ts"]
    assert "EXCHANGE_RATES" not in api_files["Dockerfile"]
    readme = api_files["README.md"]
    assert "| `exchange_rates` | `exchangeRatesClient()` of" in readme
    assert "`@/shared/api/exchange-rates` | `VITE_API_URL` |" in readme


def test_with_api_data_the_browser_calls_the_api(api_files: dict[str, str]) -> None:
    assert "src/shared/api/holidays/mock.ts" not in api_files
    http = api_files["src/shared/api/third-party.ts"]
    assert "mock-store" not in http
    assert "mockFetch" not in http
    client = api_files["src/shared/api/holidays/client.ts"]
    assert "    baseUrl: import.meta.env.VITE_HOLIDAYS_API_URL || undefined,\n" in client
    assert "  readonly VITE_HOLIDAYS_API_URL?: string;" in api_files["src/vite-env.d.ts"]
    dockerfile = api_files["Dockerfile"]
    assert "ARG VITE_HOLIDAYS_API_URL=https://date.nager.at/api/v3\n" in dockerfile
    assert "ENV VITE_HOLIDAYS_API_URL=${VITE_HOLIDAYS_API_URL}\n" in dockerfile
    assert (
        "| `holidays` | `holidaysClient()` of `@/shared/api/holidays` |" in api_files["README.md"]
    )


def test_appgen_generate_prints_the_warnings(tmp_path: Path) -> None:
    folder = tmp_path / "definition"
    shutil.copytree(EXAMPLE.parent, folder)
    definition = folder / "app.yaml"
    definition.write_text(definition.read_text().replace(EXPOSE, ""))
    runner = CliRunner()
    out = tmp_path / "out"
    result = runner.invoke(app, ["generate", str(definition), "-b", "react", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "\nWarnings: 1\n  The API 'exchange_rates' has a secret" in result.output


def test_a_binding_without_the_hook_has_no_warnings() -> None:
    result = generate(load_definition(EXAMPLE), find_binding("nextjs"))
    assert result.warnings == []
