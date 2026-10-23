import json
import os
from pathlib import Path

import pytest

from appgen.dsl import AppDefinition, load_definition
from appgen.trace import CheckReport, ReportFormat, check_traces, render

TESTS = Path(__file__).parent
CODE = TESTS / "fixtures" / "trace-check"
GOLDEN = TESTS / "golden" / "check"


@pytest.fixture
def definition() -> AppDefinition:
    return load_definition(TESTS / "fixtures" / "project-tracker.yaml")


@pytest.fixture
def report(definition: AppDefinition) -> CheckReport:
    return check_traces(definition, CODE, exclude_kinds=["param"], min_coverage=50)


@pytest.mark.parametrize(("format", "golden"), [("text", "report.txt"), ("json", "report.json")])
def test_report_matches_the_golden_file(
    report: CheckReport, format: ReportFormat, golden: str
) -> None:
    text = render(report, format)
    if os.environ.get("APPGEN_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        (GOLDEN / golden).write_text(text, newline="")
    assert text == (GOLDEN / golden).read_text()


def test_json_report_is_stable(definition: AppDefinition, report: CheckReport) -> None:
    again = check_traces(definition, CODE, exclude_kinds=["param"], min_coverage=50)

    assert render(again, "json") == render(report, "json")
    assert json.loads(render(report, "json"))["version"] == 1


def test_check_finds_the_invalid_traces_and_the_coverage(report: CheckReport) -> None:
    assert [(p.file, p.line, p.code) for p in report.invalid] == [
        ("app.py", 10, "unknown-element"),
        ("operations.ts", 4, "unknown-kind"),
    ]
    assert [e.element_id for e in report.coverage.gaps] == ["operations.complete_task"]
    assert report.coverage.total.covered == 5


def test_exit_code_is_1_if_there_is_an_invalid_trace(report: CheckReport) -> None:
    assert report.exit_code == 1


def test_exit_code_is_0_if_all_traces_are_valid(definition: AppDefinition, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# @trace app file\n")

    report = check_traces(definition, tmp_path)

    assert report.passed
    assert report.exit_code == 0
    assert render(report, "text").endswith("Result: passed.\n")


@pytest.mark.parametrize(("min_coverage", "exit_code"), [(None, 0), (6.0, 0), (7.0, 1)])
def test_min_coverage_sets_the_exit_code(
    definition: AppDefinition, tmp_path: Path, min_coverage: float | None, exit_code: int
) -> None:
    (tmp_path / "a.py").write_text("# @trace app file\n")

    report = check_traces(definition, tmp_path, min_coverage=min_coverage)

    assert report.coverage.percent == pytest.approx(100 / 15)
    assert report.exit_code == exit_code


def test_a_warning_does_not_change_the_result(definition: AppDefinition, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text('# @trace app file\nx = "@trace app"\n')

    report = check_traces(definition, tmp_path)

    assert [w.code for w in report.warnings] == ["skipped-trace"]
    assert report.passed
    assert report.exit_code == 0
    assert "Warnings: 1\n  a.py:2:6: skipped-trace:" in render(report, "text")
    assert json.loads(render(report, "json"))["warnings"][0]["line"] == 2


def test_text_gives_all_reasons_for_a_failure(report: CheckReport) -> None:
    assert render(report, "text").endswith(
        "Result: failed: 2 invalid traces and the coverage 35.7 % is lower than 50.0 %.\n"
    )


def test_a_gap_file_without_stub_markers_is_a_gap_to_close(
    definition: AppDefinition, tmp_path: Path
) -> None:
    (tmp_path / "open_ext.py").write_text(
        "# @trace:gap operations.list_tasks file\n"
        "def f():\n"
        "    # TODO(appgen): write it.\n"
        "    raise NotImplementedError\n"
    )
    (tmp_path / "written_ext.py").write_text(
        "# @trace:gap operations.complete_task file\ndef f():\n    return 1\n"
    )

    report = check_traces(definition, tmp_path)

    assert [(p.file, p.line, p.element_id) for p in report.gaps_to_close] == [
        ("written_ext.py", 1, "operations.complete_task")
    ]
    assert report.gaps_to_close[0].hint == (
        "If the code is done, change '@trace:gap operations.complete_task' to "
        "'@trace:manual operations.complete_task'."
    )
    # Both stay open gaps, and the check passes.
    assert {e.element_id for e in report.coverage.gaps} == {
        "operations.list_tasks",
        "operations.complete_task",
    }
    assert report.passed
    text = render(report, "text")
    assert "Gaps to close: 1\n  written_ext.py:1: operations.complete_task:" in text
    assert "open_ext.py" not in text.split("Gaps to close")[1]
