from dataclasses import replace
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.gen import GenerationError, Output, find_binding, generate, read_manifest, write_result
from appgen.trace.scanner import scan_folder

TESTS = Path(__file__).parent
GAP = "gaps/operations.complete_task.md"


def _definition(extra: str = "") -> AppDefinition:
    return load_definition_text(
        dedent(
            """\
            version: 0
            app: { name: tracker, title: Tracker }
            entities:
              Task:
                fields:
                  title: { type: string }
            operations:
              complete_task:
                kind: custom
                entity: Task
                description: Mark a task as done.
            """
        )
        + dedent(extra)
    )


def _generate(definition: AppDefinition, out: Path) -> None:
    binding = find_binding("minimal")
    write_result(generate(definition, binding), out, binding.name)


def test_each_uncovered_element_gets_an_extension_file_with_a_gap_trace() -> None:
    result = generate(_definition(), find_binding("minimal"))
    assert [(g.element_id, g.path) for g in result.gaps] == [("operations.complete_task", GAP)]
    gap = next(f for f in result.files if f.path == GAP)
    assert gap.kind == "extension"
    assert "<!-- @trace:gap operations.complete_task file -->" in gap.content
    assert "TODO(appgen): write the operation `complete_task` by hand." in gap.content
    assert "Mark a task as done." in gap.content


def test_an_existing_extension_file_stays_as_it_is(tmp_path: Path) -> None:
    _generate(_definition(), tmp_path)
    (tmp_path / GAP).write_text("<!-- @trace:manual operations.complete_task file -->\nDone.\n")
    _generate(_definition(), tmp_path)
    assert (tmp_path / GAP).read_text().endswith("Done.\n")


def test_hand_written_code_survives_a_change_of_the_definition(tmp_path: Path) -> None:
    _generate(_definition(), tmp_path)
    (tmp_path / GAP).write_text("<!-- @trace:manual operations.complete_task file -->\nDone.\n")

    # A new element adds a gap file and keeps the hand-written one.
    _generate(_definition("pages:\n  tasks: { path: /tasks, title: Tasks }\n"), tmp_path)
    assert (tmp_path / "gaps/pages.tasks.md").is_file()
    assert (tmp_path / GAP).read_text().endswith("Done.\n")

    # The element leaves the definition: the file stays, marked as orphaned.
    definition = load_definition_text(
        "version: 0\napp: { name: tracker, title: Tracker }\n"
        "entities:\n  Task:\n    fields:\n      title: { type: string }\n"
    )
    _generate(definition, tmp_path)
    assert (tmp_path / GAP).read_text().endswith("Done.\n")
    manifest = read_manifest(tmp_path)
    assert manifest is not None and manifest.extensions[GAP].orphaned


def test_the_output_has_no_malformed_traces(tmp_path: Path) -> None:
    definition = load_definition(TESTS / "fixtures" / "project-tracker.yaml")
    _generate(definition, tmp_path)
    scan = scan_folder(tmp_path)
    assert scan.problems == []
    assert {t.element_id for t in scan.traces} <= set(definition.elements)
    gap_traces = {t.element_id for t in scan.traces if t.kind == "gap"}
    assert "operations.complete_task" in gap_traces


def test_a_gap_file_without_a_todo_stops_the_run(tmp_path: Path) -> None:
    (tmp_path / "gap.md.j2").write_text("{{ trace_header(element_id) }}\n")
    binding = replace(
        find_binding("minimal"),
        template_dir=tmp_path,
        outputs=(),
        gap_rule=Output("gap.md.j2", "{{ element_id }}.md"),
    )
    with pytest.raises(GenerationError, match=r"without a TODO\(appgen\) comment"):
        generate(_definition(), binding)
