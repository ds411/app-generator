"""The browser clients of the third-party APIs in the React app (ADR 0019)."""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from appgen.bindings.shared.integrations import ts_apis
from appgen.cli import app
from appgen.dsl import load_definition, load_definition_text
from appgen.gen import GenerationResult, find_binding, generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def mock_result() -> GenerationResult:
    return generate(load_definition(EXAMPLE), find_binding("react"))


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
    mock_result: GenerationResult,
) -> None:
    files = _files(mock_result)
    assert not any(p.startswith("src/shared/api/exchange-rates/client.ts") for p in files)
    gap = files["src/shared/api/exchange-rates/client.ext.ts"]
    assert gap.splitlines()[1:4] == [
        "// @trace:gap apis.exchange_rates file",
        "// @trace:gap apis.exchange_rates.operations.getLatestRates file",
        "// @trace:gap apis.exchange_rates.operations.convertAmount file",
    ]
    assert "TODO(appgen)" in gap
    assert "EXCHANGE_RATES" not in files["src/shared/api/third-party.ts"]
    assert len(mock_result.warnings) == 1
    warning = mock_result.warnings[0]
    assert warning.startswith("The API 'exchange_rates' has a secret (EXCHANGE_RATES_API_KEY)")
    assert "custom operation of the FastAPI app (apis: [exchange_rates])" in warning
    assert "'x-react-data: api'" in warning


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
    assert "EXCHANGE_RATES" not in dockerfile
    assert (
        "| `holidays` | `holidaysClient()` of `@/shared/api/holidays` |" in api_files["README.md"]
    )


def test_appgen_generate_prints_the_warnings(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["generate", str(EXAMPLE), "-b", "react", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "\nWarnings: 1\n  The API 'exchange_rates' has a secret" in result.output


def test_a_binding_without_the_hook_has_no_warnings() -> None:
    result = generate(load_definition(EXAMPLE), find_binding("nextjs"))
    assert result.warnings == []
