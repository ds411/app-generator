"""The trace check on the output of the test binding (`minimal`)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from appgen.cli import app
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.gen import find_binding, generate, write_result
from appgen.trace import check_traces

TESTS = Path(__file__).parent
DEFINITION = TESTS / "fixtures" / "project-tracker.yaml"

runner = CliRunner()


@pytest.fixture
def definition() -> AppDefinition:
    return load_definition(DEFINITION)


@pytest.fixture
def output(definition: AppDefinition, tmp_path: Path) -> Path:
    out = tmp_path / "out"
    write_result(generate(definition, find_binding("minimal")), out, "minimal")
    return out


def test_output_of_the_test_binding_has_no_invalid_traces(
    definition: AppDefinition, output: Path
) -> None:
    report = check_traces(definition, output)

    assert report.invalid == []
    assert report.passed


def test_check_reads_the_traces_of_files_without_comments_from_the_manifest(
    definition: AppDefinition, output: Path
) -> None:
    report = check_traces(definition, output)

    from_manifest = [t for t in report.traces if t.file == "app.json"]
    assert from_manifest
    assert all(t.line == 0 and t.scope == "file" for t in from_manifest)


def test_manifest_lists_the_generated_files(definition: AppDefinition, output: Path) -> None:
    (output / "extra.md").write_text("<!-- @trace app file -->\n")

    report = check_traces(definition, output)

    assert [(p.file, p.code) for p in report.invalid] == [
        ("extra.md", "generated-trace-in-manual-file")
    ]


def test_check_without_the_manifest(definition: AppDefinition, output: Path) -> None:
    (output / "extra.md").write_text("<!-- @trace app file -->\n")

    report = check_traces(definition, output, use_manifest=False)

    assert report.invalid == []
    assert all(t.file != "app.json" for t in report.traces)


def test_old_output_has_invalid_traces_after_an_element_is_removed(output: Path) -> None:
    text = DEFINITION.read_text().replace("      due_date: { type: date }\n", "")
    changed = load_definition_text(text)

    report = check_traces(changed, output)

    assert [(p.file, p.code, p.element_id) for p in report.invalid] == [
        ("entities/Task.md", "unknown-element", "entities.Task.fields.due_date")
    ]
    assert report.exit_code == 1


def test_check_command_reports_the_removed_element(output: Path, tmp_path: Path) -> None:
    changed = tmp_path / "changed.yaml"
    changed.write_text(DEFINITION.read_text().replace("      due_date: { type: date }\n", ""))

    result = runner.invoke(app, ["check", str(changed), str(output), "-f", "json"])

    assert result.exit_code == 1
    invalid = json.loads(result.output)["invalid"]
    assert [(i["file"], i["element_id"]) for i in invalid] == [
        ("entities/Task.md", "entities.Task.fields.due_date")
    ]


def test_check_command_stops_on_a_broken_manifest(output: Path) -> None:
    (output / ".appgen" / "manifest.json").write_text("{}")

    result = runner.invoke(app, ["check", str(DEFINITION), str(output)])

    assert result.exit_code == 2
    assert "manifest" in result.output


def test_check_does_not_count_the_kinds_that_the_binding_excludes(
    definition: AppDefinition, tmp_path: Path
) -> None:
    binding = replace(find_binding("minimal"), excludes=frozenset({"page"}))
    write_result(generate(definition, binding), tmp_path, binding.name)

    report = check_traces(definition, tmp_path)

    assert report.excluded_kinds == ["page"]
    assert report.coverage.excluded == ["pages.projects"]
    manifest = json.loads((tmp_path / ".appgen" / "manifest.json").read_text())
    assert manifest["excluded_kinds"] == ["page"]
