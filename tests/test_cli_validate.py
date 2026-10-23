import json
from pathlib import Path

from typer.testing import CliRunner

from appgen.cli import app

EXAMPLES = Path(__file__).parent.parent / "examples"
VALID = EXAMPLES / "project-tracker" / "app.yaml"
INVALID = EXAMPLES / "invalid" / "unknown-reference.yaml"

runner = CliRunner()


def test_valid_definition_exits_with_0() -> None:
    result = runner.invoke(app, ["validate", str(VALID)])

    assert result.exit_code == 0
    assert result.output == f"{VALID}: valid.\n"


def test_invalid_definition_exits_with_1_and_lists_each_error() -> None:
    result = runner.invoke(app, ["validate", str(INVALID)])

    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[0].startswith(f"{INVALID}:8:45: error[unknown-reference]:")
    assert "(in entities.Task.relations.project)" in lines[0]
    assert lines[-1] == f"{INVALID}: 1 error."


def test_counts_all_errors(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text("app: { name: Bad }\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", str(path)])

    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == f"{path}: 4 errors."


def test_json_format_prints_the_errors_as_json() -> None:
    result = runner.invoke(app, ["validate", "--format", "json", str(INVALID)])

    assert result.exit_code == 1
    report = json.loads(result.output)
    assert report["valid"] is False
    assert report["diagnostics"] == [
        {
            "code": "unknown-reference",
            "message": "The entity 'Project' does not exist.",
            "file": str(INVALID),
            "line": 8,
            "column": 45,
            "element_id": "entities.Task.relations.project",
            "hint": None,
        }
    ]


def test_json_format_for_a_valid_definition() -> None:
    result = runner.invoke(app, ["validate", "-f", "json", str(VALID)])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"file": str(VALID), "valid": True, "diagnostics": []}


def test_missing_file_exits_with_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "missing.yaml")])

    assert result.exit_code == 1
    assert "error[file-error]" in result.output
