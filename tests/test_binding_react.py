"""Tests of the React binding: the generated files, their traces, and determinism.

The pre-push hook installs, lints, type checks, and builds the generated
app (see `scripts/check-react.sh`). These tests check the output of the
generator only, so that they need no network and no Node.js.
"""

from pathlib import Path

import pytest

from appgen.bindings.react.helpers import route_params, route_path
from appgen.dsl import AppDefinition, load_definition
from appgen.gen import (
    Binding,
    GenerationResult,
    find_binding,
    generate,
    iter_elements,
    write_result,
)
from appgen.trace import check_traces

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"


@pytest.fixture(scope="module")
def definition() -> AppDefinition:
    return load_definition(EXAMPLE)


@pytest.fixture(scope="module")
def react() -> Binding:
    return find_binding("react")


@pytest.fixture(scope="module")
def result(definition: AppDefinition, react: Binding) -> GenerationResult:
    return generate(definition, react)


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


def test_route_paths_use_the_react_router_syntax() -> None:
    assert route_path("/projects/{id}") == "/projects/:id"
    assert route_path("/") == "/"
    assert route_params("/projects/{project_id}/tasks/{id}") == ["project_id", "id"]


def test_the_app_has_the_fsd_layers(result: GenerationResult) -> None:
    layers = {path.split("/")[1] for path in _files(result) if path.startswith("src/")}
    assert {"app", "pages", "widgets", "features", "entities", "shared"} <= layers


def test_the_app_uses_react_19_vite_react_router_and_pnpm(result: GenerationResult) -> None:
    package = _files(result)["package.json"]
    assert '"react": "19.' in package
    assert '"react-router": "' in package
    assert '"vite": "' in package
    assert '"packageManager": "pnpm@' in package
    for script in ('"lint":', '"typecheck":', '"build":'):
        assert script in package
    assert '"strict": true' in _files(result)["tsconfig.json"]


def test_each_page_has_a_slice_and_a_route(
    definition: AppDefinition, result: GenerationResult
) -> None:
    files = _files(result)
    router = files["src/app/router.tsx"]
    assert '{ path: "/projects/:id", element: <ProjectDetailPage /> }' in router
    for page in definition.pages.values():
        assert f"// @trace {page.id}" in router
    assert "@trace pages.project_detail file" in files["src/pages/project-detail/index.ts"]
    assert (
        "const { id } = useParams();"
        in files["src/pages/project-detail/ui/project-detail-page.tsx"]
    )


def test_each_entity_has_a_slice_with_types_meta_mock_data_and_an_api(
    definition: AppDefinition, result: GenerationResult
) -> None:
    files = _files(result)
    for part in ("index.ts", "model/types.ts", "model/meta.ts", "api/task-api.ts"):
        assert f"src/entities/task/{part}" in files
    types = files["src/entities/task/model/types.ts"]
    assert "  dueDate: string | null; // @trace entities.Task.fields.due_date" in types
    assert "  projectId: string; // @trace entities.Task.relations.project" in types
    assert "export type TaskStatus = (typeof taskStatusValues)[number];" in types
    assert '  status: "todo",' in types
    assert (
        "  members: string[]; // @trace entities.Project.relations.members"
        in files["src/entities/project/model/types.ts"]
    )
    api = files["src/entities/task/api/task-api.ts"]
    assert "export function createTask(input: TaskInput): Promise<Task> { // @trace" in api
    assert "export function listTasksOfProject( // @trace entities.Project.relations.tasks" in api
    assert '"title": "' in files["src/entities/task/api/task-mock-data.ts"]


def test_two_runs_give_the_same_output(definition: AppDefinition, react: Binding) -> None:
    assert _files(generate(definition, react)) == _files(generate(definition, react))


def test_each_file_has_a_file_trace_and_the_check_finds_no_invalid_traces(
    tmp_path: Path, definition: AppDefinition, result: GenerationResult
) -> None:
    write_result(result, tmp_path, "react")

    report = check_traces(definition, tmp_path)

    assert report.invalid == []
    with_file_trace = {t.file for t in report.traces if t.scope == "file"}
    assert with_file_trace == {f.path for f in result.files}
    covered = {e.element_id for e in report.coverage.elements if e.status == "covered"}
    assert {"app", "pages.dashboard", "pages.project_detail"} <= covered
    for element in iter_elements(definition):
        if element.kind in ("entity", "field", "relation", "page"):
            assert element.id in covered, element.id
    for name, operation in definition.operations.items():
        if operation.kind != "custom":
            assert f"operations.{name}" in covered
