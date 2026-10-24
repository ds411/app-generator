import json
from pathlib import Path

from typer.testing import CliRunner

from appgen.cli import app

TESTS = Path(__file__).parent
DEFINITION = str(TESTS / "fixtures" / "project-tracker.yaml")
CODE = str(TESTS / "fixtures" / "trace-check")
GOLDEN = TESTS / "golden" / "check"

runner = CliRunner()


def test_check_prints_the_text_report() -> None:
    result = runner.invoke(
        app, ["check", DEFINITION, CODE, "--exclude-kind", "param", "--min-coverage", "50"]
    )

    assert result.exit_code == 1
    assert result.output == (GOLDEN / "report.txt").read_text()


def test_check_prints_the_json_report() -> None:
    result = runner.invoke(
        app,
        [
            "check",
            DEFINITION,
            CODE,
            "-f",
            "json",
            "--exclude-kind",
            "param",
            "--min-coverage",
            "50",
        ],
    )

    assert result.exit_code == 1
    assert result.output == (GOLDEN / "report.json").read_text()


def test_check_exits_with_0_if_the_check_passes(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# @trace app file\n")

    result = runner.invoke(app, ["check", DEFINITION, str(tmp_path), "--min-coverage", "5"])

    assert result.exit_code == 0
    assert result.output.endswith("Result: passed.\n")


def test_check_exits_with_1_if_the_coverage_is_too_low(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# @trace app file\n")

    result = runner.invoke(app, ["check", DEFINITION, str(tmp_path), "--min-coverage", "10"])

    assert result.exit_code == 1


def test_check_can_ignore_more_paths(tmp_path: Path) -> None:
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "a.py").write_text("# @trace nothing\n")

    result = runner.invoke(
        app, ["check", DEFINITION, str(tmp_path), "--ignore", "vendor/", "-f", "json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["files"] == 0


def test_check_exits_with_2_if_the_definition_is_not_valid(tmp_path: Path) -> None:
    definition = tmp_path / "app.yaml"
    definition.write_text("version: 0\n")

    result = runner.invoke(app, ["check", str(definition), str(tmp_path)])

    assert result.exit_code == 2
    assert "the app definition is not valid" in result.output


def test_check_needs_a_code_folder(tmp_path: Path) -> None:
    result = runner.invoke(app, ["check", DEFINITION, str(tmp_path / "missing")])

    assert result.exit_code == 2


def test_orphans_needs_an_output_manifest(tmp_path: Path) -> None:
    result = runner.invoke(app, ["orphans", DEFINITION, str(tmp_path)])

    assert result.exit_code == 2
    assert "has no output manifest" in result.output
