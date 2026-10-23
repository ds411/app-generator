"""Tests of the Next.js binding: the generated files, their traces, and determinism.

`scripts/check-nextjs.sh` installs, lints, type checks, and builds the
generated app. These tests check the output of the generator only, so
that they need no network and no Node.js.
"""

import json
from pathlib import Path

import pytest

from appgen.bindings.nextjs.model import route_dir
from appgen.dsl import AppDefinition, load_definition
from appgen.gen import Binding, GenerationResult, find_binding, generate, write_result
from appgen.trace import check_traces

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"


@pytest.fixture(scope="module")
def definition() -> AppDefinition:
    return load_definition(EXAMPLE)


@pytest.fixture(scope="module")
def nextjs() -> Binding:
    return find_binding("nextjs")


@pytest.fixture(scope="module")
def result(definition: AppDefinition, nextjs: Binding) -> GenerationResult:
    return generate(definition, nextjs)


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


def test_route_folders_use_the_app_router_syntax() -> None:
    assert route_dir("/") == ("", ())
    assert route_dir("/projects") == ("projects", ())
    assert route_dir("/projects/{project_id}/tasks/{id}") == (
        "projects/[project_id]/tasks/[id]",
        ("project_id", "id"),
    )


def test_the_app_uses_next_16_typescript_strict_and_pnpm(result: GenerationResult) -> None:
    files = _files(result)
    package = json.loads(files["package.json"])
    assert package["dependencies"]["next"].startswith("16.")
    assert package["packageManager"].startswith("pnpm@")
    assert {"lint", "typecheck", "build"} <= set(package["scripts"])
    assert json.loads(files["tsconfig.json"])["compilerOptions"]["strict"] is True
    assert 'output: "standalone"' in files["next.config.ts"]


def test_the_fsd_layers_are_in_src_and_the_routes_in_app(result: GenerationResult) -> None:
    files = _files(result)
    layers = {path.split("/")[1] for path in files if path.startswith("src/")}
    assert {"app", "pages", "widgets", "features", "entities", "shared"} <= layers
    assert "pages/README.md" in files
    routes = sorted(path for path in files if path.startswith("app/"))
    assert routes == [
        "app/layout.tsx",
        "app/page.tsx",
        "app/people/page.tsx",
        "app/projects/[id]/page.tsx",
        "app/projects/page.tsx",
        "app/tasks/[id]/page.tsx",
        "app/tasks/page.tsx",
    ]


def test_each_route_renders_the_page_of_its_slice(result: GenerationResult) -> None:
    files = _files(result)
    route = files["app/projects/[id]/page.tsx"]
    assert "// @trace pages.project_detail file" in route
    assert 'import { ProjectDetailPage } from "@/pages/project-detail";' in route
    assert "return <ProjectDetailPage params={await params} />;" in route
    assert "export { DashboardPage }" in files["src/pages/dashboard/index.ts"]


def test_uncovered_elements_get_gap_files(result: GenerationResult) -> None:
    gap = _files(result)["src/gaps/operations.complete_task.ext.ts"]
    assert "// @trace:gap operations.complete_task file" in gap
    assert "TODO(appgen)" in gap
    assert {g.kind for g in result.gaps} >= {"entity", "field", "operation"}


def test_two_runs_give_the_same_output(definition: AppDefinition, nextjs: Binding) -> None:
    assert _files(generate(definition, nextjs)) == _files(generate(definition, nextjs))


def test_each_file_has_a_trace_and_the_check_finds_no_invalid_traces(
    tmp_path: Path, definition: AppDefinition, result: GenerationResult
) -> None:
    write_result(result, tmp_path, "nextjs")

    report = check_traces(definition, tmp_path)

    assert report.invalid == []
    with_file_trace = {t.file for t in report.traces if t.scope == "file"}
    assert with_file_trace == {f.path for f in result.files}
    covered = {e.element_id for e in report.coverage.elements if e.status == "covered"}
    assert {"app", "pages.dashboard", "pages.project_detail"} <= covered
