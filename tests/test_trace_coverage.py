from pathlib import Path

import pytest

from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.trace import Trace, compute_coverage, scan_text

TESTS = Path(__file__).parent


@pytest.fixture
def definition() -> AppDefinition:
    return load_definition(TESTS / "fixtures" / "project-tracker.yaml")


def _traces(text: str) -> list[Trace]:
    traces, problems = scan_text(text, "app.py")
    assert problems == []
    return traces


def test_elements_without_traces_are_uncovered(definition: AppDefinition) -> None:
    report = compute_coverage(definition, [])

    assert len(report.uncovered) == len(definition.elements)
    assert report.gaps == []
    assert report.percent == 0.0


def test_generated_and_manual_traces_cover_an_element(definition: AppDefinition) -> None:
    traces = _traces("# @trace app file\n# @trace:manual pages.projects\nx = 1\n")

    report = compute_coverage(definition, traces)

    covered = [e.element_id for e in report.elements if e.status == "covered"]
    assert covered == ["app", "pages.projects"]


def test_an_element_with_only_gap_traces_is_an_open_gap(definition: AppDefinition) -> None:
    traces = _traces(
        "# @trace:gap operations.complete_task file\n"
        "# @trace:gap operations.list_tasks\n"
        "x = 1  # @trace:manual operations.list_tasks\n"
    )

    report = compute_coverage(definition, traces)

    assert [e.element_id for e in report.gaps] == ["operations.complete_task"]
    status = {e.element_id: e.status for e in report.elements}
    assert status["operations.list_tasks"] == "covered"


def test_a_trace_covers_only_its_own_element(definition: AppDefinition) -> None:
    report = compute_coverage(definition, _traces("# @trace entities.Task file\n"))

    status = {e.element_id: e.status for e in report.elements}
    assert status["entities.Task"] == "covered"
    assert status["entities.Task.fields.title"] == "uncovered"


def test_element_keeps_its_traces(definition: AppDefinition) -> None:
    traces = _traces("# @trace app file\nx = 1  # @trace app\n")

    report = compute_coverage(definition, traces)

    assert report.elements[0].traces == tuple(traces)


def test_traces_to_unknown_ids_do_not_change_the_coverage(definition: AppDefinition) -> None:
    report = compute_coverage(definition, _traces("# @trace entities.Nothing file\n"))

    assert report.total.covered == 0


def test_gives_the_coverage_in_total_and_for_each_kind(definition: AppDefinition) -> None:
    traces = _traces(
        "# @trace app file\n"
        "# @trace entities.Project\n"
        "# @trace entities.Task\n"
        "# @trace entities.Task.fields.title\n"
        "# @trace:gap pages.projects\n"
    )

    report = compute_coverage(definition, traces)

    counts = {k.kind: (k.covered, k.gaps, k.uncovered) for k in report.by_kind}
    assert counts == {
        "app": (1, 0, 0),
        "entity": (2, 0, 0),
        "field": (1, 0, 4),
        "relation": (0, 0, 2),
        "operation": (0, 0, 3),
        "param": (0, 0, 1),
        "page": (0, 1, 0),
    }
    percents = {k.kind: k.percent for k in report.by_kind}
    assert percents["entity"] == 100.0
    assert percents["field"] == 20.0
    assert (report.total.covered, report.total.total) == (4, 15)
    assert report.percent == pytest.approx(100 * 4 / 15)


def test_excluded_kinds_and_their_children_do_not_count(definition: AppDefinition) -> None:
    report = compute_coverage(definition, [], exclude_kinds=["page", "operation"])

    assert report.excluded == [
        "operations.create_task",
        "operations.list_tasks",
        "operations.complete_task",
        "operations.complete_task.params.note",
        "pages.projects",
    ]
    assert {k.kind for k in report.by_kind} == {"app", "entity", "field", "relation"}
    assert report.total.total == 10


def test_can_exclude_the_ui_elements() -> None:
    definition = load_definition_text(
        "version: 0\n"
        "app: { name: a, title: A }\n"
        "entities:\n"
        "  Task:\n"
        "    fields: { title: { type: string } }\n"
        "ui:\n"
        "  tokens:\n"
        "    color:\n"
        '      white: { $value: "#ffffff" }\n'
    )

    report = compute_coverage(definition, [], exclude_kinds=["ui"])

    assert report.excluded == ["ui", "ui.tokens", "ui.tokens.color", "ui.tokens.color.white"]
    assert [e.element_id for e in report.elements] == [
        "app",
        "entities.Task",
        "entities.Task.fields.title",
    ]


def test_an_empty_coverage_is_complete(definition: AppDefinition) -> None:
    report = compute_coverage(definition, [], exclude_kinds=["app", "entity", "operation", "page"])

    assert report.total.total == 0
    assert report.percent == 100.0
