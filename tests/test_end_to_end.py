"""One definition, three apps: generate and check each app of the project tracker.

The proof of concept generates a full-stack app (Next.js), a back-end app
(FastAPI), and a front-end app (React) from the same definition. Each app
is standalone. These tests run the CLI as an app author does: `appgen
generate`, then `appgen check`.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from appgen.cli import app

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

runner = CliRunner()

# The element kinds that each binding leaves out by design. A back-end
# app has no pages and no UI.
BY_DESIGN: dict[str, list[str]] = {
    "nextjs": [],
    "react": [],
    "fastapi": ["page", "ui"],
}

# The stubs that each app has after a first run: the custom operations,
# and in the front ends the custom UI elements.
CUSTOM_OPERATIONS = {
    "operations.archive_project",
    "operations.assign_task",
    "operations.complete_task",
}
CUSTOM_UI = {
    "ui.views.task_detail.tabs.activity",
    "ui.views.project_detail.tabs.timeline",
    "ui.forms.assign_task.fields.assignee_id",
    "ui.forms.assign_task.rules.active_person",
    "ui.dashboards.overview.widgets.workload",
}
OPEN_GAPS: dict[str, set[str]] = {
    "nextjs": CUSTOM_OPERATIONS | CUSTOM_UI,
    "react": CUSTOM_OPERATIONS | CUSTOM_UI,
    "fastapi": CUSTOM_OPERATIONS,
}


@pytest.fixture(scope="module", params=sorted(BY_DESIGN))
def checked(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Any:
    binding: str = request.param
    out = tmp_path_factory.mktemp(binding)
    generated = runner.invoke(app, ["generate", str(EXAMPLE), "-b", binding, "-o", str(out)])
    assert generated.exit_code == 0, generated.output
    result = runner.invoke(app, ["check", str(EXAMPLE), str(out), "-f", "json"])
    return binding, result.exit_code, json.loads(result.output)


def test_the_check_of_each_app_passes(checked: Any) -> None:
    _, exit_code, report = checked
    assert exit_code == 0
    assert report["passed"] is True
    assert report["invalid"] == []


def test_each_app_covers_all_elements_except_the_kinds_out_of_its_scope(checked: Any) -> None:
    binding, _, report = checked
    assert report["coverage"]["excluded_kinds"] == BY_DESIGN[binding]
    assert report["uncovered"] == []
    coverage = report["coverage"]
    assert coverage["covered"] + coverage["gaps"] == coverage["total"]


def test_each_app_reports_its_stubs_as_open_gaps(checked: Any) -> None:
    binding, _, report = checked
    gaps = {g["id"] for g in report["gaps"]}
    assert gaps == OPEN_GAPS[binding]
    assert report["coverage"]["gaps"] == len(gaps)
    for gap in report["gaps"]:
        files = [t["file"] for t in gap["traces"]]
        assert len(files) == 1
        assert ".ext." in files[0] or files[0].endswith("_ext.py")


def test_each_app_traces_the_entities_and_the_operations(checked: Any) -> None:
    _, _, report = checked
    kinds = {k["kind"]: k for k in report["coverage"]["by_kind"]}
    for kind in ("app", "entity", "field", "relation", "operation"):
        assert kinds[kind]["uncovered"] == 0
        assert kinds[kind]["covered"] > 0
