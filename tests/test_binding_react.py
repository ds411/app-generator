"""Tests of the React binding: the generated files, their traces, and determinism.

The pre-push hook installs, lints, type checks, and builds the generated
app (see `scripts/check-react.sh`). These tests check the output of the
generator only, so that they need no network and no Node.js.
"""

from pathlib import Path

import pytest

from appgen.bindings.react import versions
from appgen.bindings.react.helpers import route_params, route_path
from appgen.bindings.shared import shadcn
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


def test_the_app_has_only_the_shadcn_components_that_the_ui_uses(react: Binding) -> None:
    files = _files(
        generate(load_definition(EXAMPLE.parent.parent / "edge-cases" / "app.yaml"), react)
    )
    components = sorted(p for p in files if p.startswith("src/shared/ui/"))
    assert components == ["src/shared/ui/button.tsx", "src/shared/ui/sonner.tsx"]
    assert '"radix-ui": "' in files["package.json"]
    assert '"recharts"' not in files["package.json"]
    assert '"@/shared/lib/theme"' in files["src/shared/ui/sonner.tsx"]


def test_the_shadcn_setup_follows_the_definition(
    definition: AppDefinition, result: GenerationResult
) -> None:
    files = _files(result)
    for name in [c.name for c in shadcn.used_components(definition)]:
        assert f"src/shared/ui/{name}.tsx" in files
    assert "src/shared/lib/use-mobile.ts" in files
    assert '"css": "src/app/styles/index.css"' in files["components.json"]
    assert '"ui": "@/shared/ui"' in files["components.json"]
    assert "plugins: [react(), tailwindcss()]" in files["vite.config.ts"]
    assert '@import "tailwindcss";' in files["src/app/styles/index.css"]
    assert '"recharts": "' in files["package.json"]


def test_each_package_of_the_shadcn_components_has_a_version() -> None:
    names = shadcn.packages(shadcn.registry().values())
    assert sorted(set(names) - set(versions.COMPONENT_PACKAGES)) == []


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


GAPS = Path(__file__).parent / "fixtures" / "react-gaps.yaml"

GAP_FILES = {
    "operations.publish_note": "src/features/publish-note/api/publish-note",
    "pages.report.content": "src/pages/report/ui/report-content",
    "pages.note_report.content": "src/pages/note-report/ui/note-report-content",
    "ui.views.note_detail.tabs.graph": "src/widgets/note-detail/ui/graph-tab",
    "ui.views.note_detail.sections.history": "src/widgets/note-detail/ui/history-section",
    "ui.views.note_detail.tabs.more.sections.stats": (
        "src/widgets/note-detail/ui/more-stats-section"
    ),
    "ui.dashboards.home.widgets.chart": "src/widgets/home/ui/chart-widget",
    "ui.forms.new_note.fields.title": "src/features/new-note-form/ui/title-widget",
    "ui.forms.new_note.rules.nice": "src/features/new-note-form/model/nice-rule",
    "pages.notes.actions.export": "src/features/notes-actions/model/export-action",
    "ui.layouts.shell.topbar.actions.help": "src/features/shell-actions/model/help-action",
    "ui.views.note_table.row_actions.share": (
        "src/features/note-table-actions/model/row-share-action"
    ),
    "ui.views.note_table.bulk_actions.tag": "src/features/note-table-actions/model/bulk-tag-action",
    "ui.views.note_detail.actions.print": "src/features/note-detail-actions/model/print-action",
}


def test_each_custom_element_has_a_generated_file_and_an_extension_file(react: Binding) -> None:
    files = {f.path: f for f in generate(load_definition(GAPS), react).files}

    for element_id, base in GAP_FILES.items():
        suffix = ".ts" if "/api/" in base or "/model/" in base else ".tsx"
        generated, extension = files[base + ".gen" + suffix], files[base + ".ext" + suffix]
        assert generated.kind == "generated"
        assert f"@trace {element_id} file" in generated.content
        assert f'from "./{base.rsplit("/", 1)[1]}.ext";' in generated.content
        assert extension.kind == "extension"
        assert f"@trace:gap {element_id} file" in extension.content
        assert "TODO(appgen):" in extension.content
    assert len([f for f in files.values() if f.kind == "extension"]) == len(GAP_FILES)


def test_the_gaps_have_typed_signatures(react: Binding) -> None:
    files = _files(generate(load_definition(GAPS), react))

    assert (
        "export async function publishNote(id: string): Promise<void> {"
        in files["src/features/publish-note/api/publish-note.gen.ts"]
    )
    assert (
        "_records: Note[]" in files["src/features/note-table-actions/model/bulk-tag-action.ext.ts"]
    )
    assert "value: string | null;" in files["src/features/new-note-form/ui/title-widget.gen.tsx"]
    assert (
        "_values: Partial<NoteInput>" in files["src/features/new-note-form/model/nice-rule.ext.ts"]
    )
    page = files["src/pages/note-report/ui/note-report-page.tsx"]
    assert "<NoteReportContent params={params} />" in page


def test_regeneration_keeps_the_code_in_the_extension_files(
    tmp_path: Path, definition: AppDefinition, react: Binding
) -> None:
    write_result(generate(definition, react), tmp_path, "react")
    extension = tmp_path / "src/widgets/task-detail/ui/activity-tab.ext.tsx"
    hand_written = extension.read_text().replace("@trace:gap", "@trace:manual")
    extension.write_text(hand_written)

    write_result(generate(definition, react), tmp_path, "react")

    assert extension.read_text() == hand_written
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    statuses = {e.element_id: e.status for e in report.coverage.elements}
    assert statuses["ui.views.task_detail.tabs.activity"] == "covered"
    assert statuses["operations.assign_task.params.note"] == "covered"
