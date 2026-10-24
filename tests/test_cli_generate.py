import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from appgen.cli import app
from appgen.gen import MANIFEST_PATH

runner = CliRunner()
TESTS = Path(__file__).parent
DEFINITION = TESTS / "fixtures" / "project-tracker.yaml"
GOLDEN = TESTS / "golden" / "minimal"
EXAMPLE = TESTS.parent / "examples" / "project-tracker" / "app.yaml"


def _files(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _generate(
    out: Path, *extra: str, definition: Path = DEFINITION, binding: str = "minimal"
) -> tuple[int, str]:
    result = runner.invoke(
        app, ["generate", str(definition), "--binding", binding, "--out", str(out), *extra]
    )
    return result.exit_code, result.output


def test_generate_writes_the_app_and_a_summary(tmp_path: Path) -> None:
    code, output = _generate(tmp_path)
    assert code == 0, output
    assert "Generated 'project-tracker' with the binding 'minimal'" in output
    assert "Files written: 4\n  app.json\n  entities/Project.md\n" in output
    assert "Files deleted: 0" in output
    assert "Gaps created: 7\n" in output
    assert "  operations.complete_task -> gaps/operations.complete_task.md\n" in output
    files = _files(tmp_path)
    assert MANIFEST_PATH in files
    assert {k: v for k, v in files.items() if k != MANIFEST_PATH} == _files(GOLDEN)


def test_two_runs_give_the_same_output(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    assert _generate(first)[0] == 0
    assert _generate(second)[0] == 0
    assert _files(first) == _files(second)
    code, output = _generate(first)
    assert code == 0
    assert "Files written: 0" in output
    assert "Files unchanged: 4" in output
    assert "Gaps created: 0" in output
    assert "Gaps kept (extension files exist): 7" in output


def test_an_invalid_definition_writes_no_file_and_exits_with_1(tmp_path: Path) -> None:
    definition = tmp_path / "bad.yaml"
    definition.write_text("version: 0\napp: { name: x }\nentities: {}\n")
    out = tmp_path / "out"
    code, output = _generate(out, definition=definition)
    assert code == 1
    assert "no file is written" in output
    assert not out.exists()


def test_an_unknown_binding_exits_with_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["generate", str(DEFINITION), "--binding", "cobol", "--out", str(tmp_path / "o")]
    )
    assert result.exit_code == 1
    assert "The binding 'cobol' does not exist" in result.output


def test_manual_edits_stop_the_run_unless_force_is_set(tmp_path: Path) -> None:
    assert _generate(tmp_path)[0] == 0
    (tmp_path / "index.md").write_text("edited\n")
    code, output = _generate(tmp_path)
    assert code == 1
    assert "changed by hand: index.md" in output
    code, output = _generate(tmp_path, "--force")
    assert code == 0
    assert "Files written: 1\n  index.md\n" in output


def test_the_trace_check_passes_on_the_generated_app(tmp_path: Path) -> None:
    assert _generate(tmp_path)[0] == 0
    result = runner.invoke(app, ["check", str(DEFINITION), str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Result: passed." in result.output


def _created_gaps(output: str) -> dict[str, str]:
    """Return the files of each element under `Gaps created` in a summary."""
    block = output.split("Gaps created: ")[1]
    count, *lines = block.split("\n")
    return dict(line.strip().split(" -> ") for line in lines[: int(count)])


@pytest.mark.parametrize("binding", ["fastapi", "nextjs", "react"])
@pytest.mark.parametrize("definition", [DEFINITION, EXAMPLE], ids=["fixture", "example"])
def test_the_created_gaps_are_the_open_gaps_of_the_check(
    tmp_path: Path, binding: str, definition: Path
) -> None:
    # The stubs of the custom elements are extension files with a gap trace.
    code, output = _generate(tmp_path, definition=definition, binding=binding)
    assert code == 0, output
    created = _created_gaps(output)
    result = runner.invoke(app, ["check", str(definition), str(tmp_path), "--format", "json"])
    report = json.loads(result.output)

    assert set(created) == {gap["id"] for gap in report["gaps"]}
    assert "operations.complete_task" in created
    other = output.partition("Extension files created:")[2]
    assert not any(path in other for path in created.values())

    code, output = _generate(tmp_path, definition=definition, binding=binding)
    assert code == 0, output
    assert "Gaps created: 0\n" in output
    kept = re.search(r"Gaps kept \(extension files exist\): (\d+)", output)
    assert kept and int(kept.group(1)) == len(created)
    assert "Extension files created" not in output


def test_the_summary_lists_each_gap_of_an_extension_file(tmp_path: Path) -> None:
    # A browser app has no client for an API with a secret: one stub has
    # a gap for the API and for each of its operations.
    code, output = _generate(tmp_path, definition=EXAMPLE, binding="react")
    assert code == 0, output
    created = _created_gaps(output)

    client = "src/shared/api/exchange-rates/client.ext.ts"
    assert [e for e, path in created.items() if path == client] == [
        "apis.exchange_rates",
        "apis.exchange_rates.operations.getLatestRates",
        "apis.exchange_rates.operations.convertAmount",
    ]
