"""Tests of the Next.js binding: the generated files, their traces, and determinism.

`scripts/check-nextjs.sh` installs, lints, type checks, and builds the
generated app. These tests check the output of the generator only, so
that they need no network and no Node.js.
"""

import json
from pathlib import Path

import pytest

from appgen.bindings.nextjs import versions
from appgen.bindings.nextjs.model import route_dir
from appgen.bindings.shared import shadcn
from appgen.bindings.shared.mock_data import mock_data
from appgen.dsl import AppDefinition, load_definition, load_definition_text
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
EDGE_CASES = EXAMPLE.parent.parent / "edge-cases" / "app.yaml"


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
    assert '"standalone"' in files["next.config.ts"]


def test_the_fsd_layers_are_in_src_and_the_routes_in_app(result: GenerationResult) -> None:
    files = _files(result)
    layers = {path.split("/")[1] for path in files if path.startswith("src/")}
    assert {"app", "pages", "widgets", "features", "entities", "shared"} <= layers
    assert "pages/README.md" in files
    routes = sorted(path for path in files if path.startswith("app/"))
    assert routes == [
        "app/(app-shell)/exchange-rates/page.tsx",
        "app/(app-shell)/holidays/page.tsx",
        "app/(app-shell)/holidays/upcoming/page.tsx",
        "app/(app-shell)/layout.tsx",
        "app/(app-shell)/page.tsx",
        "app/(app-shell)/people/page.tsx",
        "app/(app-shell)/projects/[id]/page.tsx",
        "app/(app-shell)/projects/page.tsx",
        "app/(app-shell)/tasks/[id]/page.tsx",
        "app/(app-shell)/tasks/page.tsx",
        "app/health/route.ts",
        "app/layout.tsx",
        "app/not-found.tsx",
    ]


def test_each_route_renders_the_page_of_its_slice(result: GenerationResult) -> None:
    files = _files(result)
    route = files["app/(app-shell)/projects/[id]/page.tsx"]
    assert "// @trace pages.project_detail file" in route
    assert 'import { ProjectDetailPage } from "@/pages/project-detail";' in route
    assert "return <ProjectDetailPage />;" in route
    assert "export { DashboardPage }" in files["src/pages/dashboard/index.ts"]
    page = files["src/pages/project-detail/ui/project-detail-page.tsx"]
    assert '"use client";' in page
    assert "const { id } = useParams();" in page
    assert "<PageHeader" in page


def test_each_layout_is_a_route_group_with_the_shared_shell(result: GenerationResult) -> None:
    files = _files(result)
    group = files["app/(app-shell)/layout.tsx"]
    assert "// @trace ui.layouts.app_shell file" in group
    assert "return <AppShellLayout>{children}</AppShellLayout>;" in group
    assert "export function AppShellLayout(" in files["src/widgets/layouts/ui/app-shell-layout.tsx"]
    assert "<AppShellLayout>\n      <NotFoundPage />" in files["app/not-found.tsx"]
    router = files["src/shared/lib/router.tsx"]
    assert 'import NextLink from "next/link";' in router
    for name in ("Link", "useNavigate", "usePathname", "useParams"):
        assert f"export function {name}(" in router
    assert "src/widgets/navigation/ui/main-menu.tsx" in files
    assert "src/widgets/page-breadcrumbs/ui/page-breadcrumbs.tsx" in files


def test_pages_without_a_layout_are_in_the_bare_group(edge_files: dict[str, str]) -> None:
    assert "app/(bare)/samples/page.tsx" in edge_files
    bare = edge_files["app/(bare)/layout.tsx"]
    assert '<span className="font-semibold">{appConfig.title}</span>' in bare


def test_the_binding_covers_each_element_of_the_project_tracker(result: GenerationResult) -> None:
    assert result.gaps == []
    assert not [path for path in _files(result) if path.startswith("src/gaps/")]


def test_page_and_top_bar_actions_are_widgets(result: GenerationResult) -> None:
    files = _files(result)
    page = files["src/pages/task-detail/ui/task-detail-page.tsx"]
    assert "actions={<TaskDetailPageActions />}" in page
    actions = files["src/widgets/page-actions/ui/task-detail-actions.tsx"]
    assert "// @trace pages.task_detail.actions.delete" in actions
    assert "// @trace pages.task_detail.actions.delete.confirm" in actions
    assert 'const id = useParams()["id"] ?? "";' in actions
    assert "disabled={!record}" in actions
    layout = files["src/widgets/layouts/ui/app-shell-layout.tsx"]
    assert "<AppShellTopbarActions />" in layout
    topbar = files["src/widgets/layouts/ui/app-shell-topbar-actions.tsx"]
    assert "// @trace ui.layouts.app_shell.topbar.actions.new_task" in topbar
    assert "routeParams={routeParams}" in topbar


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


def test_the_app_has_only_the_shadcn_components_that_the_ui_uses(
    result: GenerationResult, nextjs: Binding
) -> None:
    files = _files(result)
    components = {p.removeprefix("src/shared/ui/") for p in files if p.startswith("src/shared/ui/")}
    assert {"sidebar.tsx", "table.tsx", "dialog.tsx", "chart.tsx"} <= components
    assert "@trace app file" in files["src/shared/ui/button.tsx"]
    assert 'from "@/shared/lib/utils"' in files["src/shared/ui/button.tsx"]
    assert 'from "@/shared/lib/theme"' in files["src/shared/ui/sonner.tsx"]
    aliases = json.loads(files["components.json"])["aliases"]
    assert aliases["ui"] == "@/shared/ui"

    plain = load_definition_text(
        "version: 0\n"
        "app: { name: plain, title: Plain }\n"
        "entities:\n"
        "  Note: { fields: { text: { type: text } } }\n"
    )
    plain_files = _files(generate(plain, nextjs))
    assert sorted(p for p in plain_files if p.startswith("src/shared/ui/")) == [
        "src/shared/ui/button.tsx",
        "src/shared/ui/sonner.tsx",
    ]
    package = json.loads(plain_files["package.json"])
    assert "recharts" not in package["dependencies"]
    assert "sonner" in package["dependencies"]


def test_each_component_package_has_a_version() -> None:
    needed = shadcn.packages(shadcn.registry().values())
    assert sorted(set(needed) - set(versions.COMPONENT_PACKAGES)) == []


def test_the_theme_comes_from_the_tokens(result: GenerationResult) -> None:
    files = _files(result)
    css = files["src/app/styles/globals.css"]
    assert "--primary: oklch(0.511 0.262 276.966); /* @trace ui.tokens.color.primary */" in css
    assert ".dark {" in css
    assert "--spacing-4: 1rem; /* @trace ui.tokens.spacing.4 */" in css
    assert "@utility typography-heading {" in css
    providers = files["src/app/providers/index.tsx"]
    assert 'defaultTheme="system"' in providers
    assert "@trace ui.theme file" in providers
    assert "export function ModeToggle()" in files["src/features/toggle-theme/ui/mode-toggle.tsx"]


def test_the_check_covers_all_tokens(tmp_path: Path, result: GenerationResult) -> None:
    definition = load_definition(EXAMPLE)
    write_result(result, tmp_path, "nextjs")
    report = check_traces(definition, tmp_path)
    tokens = [e for e in report.coverage.elements if e.element_id.startswith("ui.tokens")]
    assert tokens
    assert {e.status for e in tokens} == {"covered"}


def test_each_entity_is_a_drizzle_table_with_traces(result: GenerationResult) -> None:
    files = _files(result)
    task = files["src/shared/db/schema/task.ts"]
    assert "// @trace entities.Task file" in task
    assert 'export const taskTable = pgTable("task", {' in task
    assert "  // @trace entities.Task.fields.title\n" in task
    assert 'title: varchar("title", { length: 200 }).notNull(),' in task
    assert 'status: taskStatusEnum("status").default("todo"),' in task
    assert (
        'estimateHours: numeric("estimate_hours", { precision: 6, scale: 1, mode: "number" }),'
        in task
    )
    assert 'completedAt: timestamp("completed_at", { withTimezone: true, mode: "date" }),' in task
    assert (
        'projectId: uuid("project_id").notNull()'
        '.references((): AnyPgColumn => projectTable.id, { onDelete: "cascade" }),'
    ) in task
    assert (
        'assigneeId: uuid("assignee_id")'
        '.references((): AnyPgColumn => personTable.id, { onDelete: "set null" }),'
    ) in task
    assert 'comments: many(commentTable, { relationName: "Comment.task" }),' in task
    index = files["src/shared/db/schema/index.ts"]
    assert 'export * from "./task"; // @trace entities.Task' in index


def test_a_many_to_many_relation_gets_a_join_table(result: GenerationResult) -> None:
    project = _files(result)["src/shared/db/schema/project.ts"]
    assert 'export const projectMembersTable = pgTable(\n  "project_members",' in project
    assert "(t) => [primaryKey({ columns: [t.projectId, t.personId] })]," in project
    assert 'members: many(projectMembersTable, { relationName: "Project.members" }),' in project


def test_the_app_has_drizzle_kit_and_migrates_on_start(result: GenerationResult) -> None:
    files = _files(result)
    package = json.loads(files["package.json"])
    assert {"drizzle-orm", "postgres", "server-only"} <= set(package["dependencies"])
    assert package["scripts"]["db:generate"] == "drizzle-kit generate"
    assert 'schema: "./src/shared/db/schema/index.ts"' in files["drizzle.config.ts"]
    assert 'process.env.DATABASE_MIGRATE === "true"' in files["instrumentation.ts"]
    assert "DATABASE_URL=postgres://" in files[".env.example"]


def test_the_check_covers_all_entities_fields_and_relations(
    tmp_path: Path, definition: AppDefinition, result: GenerationResult
) -> None:
    write_result(result, tmp_path, "nextjs")
    report = check_traces(definition, tmp_path)
    data = [e for e in report.coverage.elements if e.element_id.startswith("entities.")]
    assert {e.status for e in data} == {"covered"}


@pytest.fixture(scope="module")
def edge_files(nextjs: Binding) -> dict[str, str]:
    return _files(generate(load_definition(EDGE_CASES), nextjs))


def test_inverse_relations_are_stored_once(edge_files: dict[str, str]) -> None:
    owner = edge_files["src/shared/db/schema/owner.ts"]
    profile = edge_files["src/shared/db/schema/profile.ts"]
    tag = edge_files["src/shared/db/schema/tag.ts"]
    # The required side of a one_to_one relation has the foreign key.
    assert 'profileId: uuid("profile_id").notNull().unique()' in owner
    assert "ownerId" not in profile
    assert "  owner: one(ownerTable),\n" in profile
    # A many_to_many relation and its inverse share one join table.
    assert '"owner_tags"' in owner
    assert "pgTable(" in tag and '"tag_owners"' not in tag
    assert 'owners: many(ownerTagsTable, { relationName: "Tag.owners" }),' in tag
    assert 'relationName: "Tag.owners",\n  }),' in owner


def test_a_table_can_refer_to_itself(edge_files: dict[str, str]) -> None:
    item = edge_files["src/shared/db/schema/item.ts"]
    assert '.references((): AnyPgColumn => itemTable.id, { onDelete: "restrict" })' in item
    assert "import { type AnyPgColumn, pgTable, text, uuid }" in item


def test_a_datetime_default_is_a_date(edge_files: dict[str, str]) -> None:
    sample = edge_files["src/shared/db/schema/sample.ts"]
    assert '.default(new Date("2026-01-31T12:00:00+00:00"))' in sample
    assert 'import { relations } from "drizzle-orm";' not in sample


def test_each_entity_has_a_repository_and_server_actions(result: GenerationResult) -> None:
    files = _files(result)
    repository = files["src/entities/project/api/project-repository.ts"]
    assert 'import "server-only";' in repository
    assert "export const projectRepository = new Repository<Project, ProjectInput>({" in repository
    assert 'key: "members",' in repository
    assert "// @trace entities.Project.relations.members begin" in repository
    actions = files["src/entities/project/api/project-actions.ts"]
    assert actions.splitlines()[2] == '"use server";'
    assert "projectRepository.create(projectInputSchema.parse(input)), { changes: true }" in actions
    assert "projectRepository.list(parseListQuery<Project>(query))" in actions
    api = files["src/entities/project/api/project-api.ts"]
    assert 'createEntityApi("Project", {' in api
    assert "export function createProject(input: ProjectInput): Promise<Project> {" in api
    assert "// @trace operations.create_project" in api
    task_api = files["src/entities/task/api/task-api.ts"]
    assert "export function listTasksOfProject(" in task_api
    assert files["src/entities/project/server.ts"].endswith(
        'export { projectRepository } from "./api/project-repository";\n'
    )


def test_the_entity_slice_has_the_api_of_the_shared_ui(result: GenerationResult) -> None:
    index = _files(result)["src/entities/task/index.ts"]
    for name in ("taskApi", "createTask", "listTasksOfProject", "taskMeta"):
        assert f"  {name},\n" in index or f"{{ {name} }}" in index
    assert "  taskInputSchema,\n  taskPatchSchema,\n  assignTaskParamsSchema,\n" in index
    assert 'export * from "./model/types";' in index
    assert "Repository" not in index


def test_the_zod_schemas_come_from_the_field_rules(
    result: GenerationResult, edge_files: dict[str, str]
) -> None:
    task = _files(result)["src/entities/task/model/schema.ts"]
    assert "title: z.string().min(1).max(200), // @trace entities.Task.fields.title" in task
    assert "status: z.enum(taskStatusValues).optional()," in task
    assert "projectId: z.uuid(), // @trace entities.Task.relations.project" in task
    assert "}) satisfies z.ZodType<TaskInput>;" in task
    assert "export const taskPatchSchema = taskInputSchema.partial();" in task
    assert (
        "note: z.string().max(500).nullish(), // @trace operations.assign_task.params.note" in task
    )
    sample = edge_files["src/entities/sample/model/schema.ts"]
    assert 'code: z.string().min(3).max(12).regex(new RegExp("^[A-Z0-9-]+$")),' in sample
    assert "count: z.int32().min(-10).max(10).optional()," in sample
    assert "ratio: z.number().min(0).max(1).optional()," in sample
    assert "moment: z.iso.datetime({ offset: true }).optional()," in sample
    assert "contact: z.email().max(254).nullable().optional()," in sample
    assert "payload: z.json().optional()," in sample
    owner = edge_files["src/entities/owner/model/schema.ts"]
    assert "tags: z.array(z.uuid()).optional()," in owner


def test_a_custom_operation_is_a_server_action_that_calls_a_gap(
    result: GenerationResult,
) -> None:
    files = _files(result)
    base = "src/features/assign-task/api/assign-task"
    action = files[base + ".gen.ts"]
    assert '"use server";' in action
    assert "const record = await taskRepository.get(idSchema.parse(id));" in action
    assert "return assignTask(record, assignTaskParamsSchema.parse(params));" in action
    ext = files[base + ".ext.ts"]
    assert "// @trace:gap operations.assign_task file" in ext
    assert "TODO(appgen)" in ext
    assert (
        "export async function assignTask(_record: Task, _params: AssignTaskParams): Promise<Task>"
        in ext
    )
    client = files[base + "-api.ts"]
    assert "export async function assignTask(id: string, params: AssignTaskParams)" in client
    assert "notifyChange();" in client
    extensions = {f.path for f in result.files if f.kind == "extension"}
    assert base + ".ext.ts" in extensions
    assert (
        'export { assignTask } from "./api/assign-task-api";'
        in files["src/features/assign-task/index.ts"]
    )


def test_the_edge_cases_cover_all_elements_with_data(tmp_path: Path, nextjs: Binding) -> None:
    definition = load_definition(EDGE_CASES)
    write_result(generate(definition, nextjs), tmp_path, "nextjs")
    report = check_traces(definition, tmp_path)
    assert not report.invalid
    data = [
        e for e in report.coverage.elements if e.element_id.startswith(("entities.", "operations."))
    ]
    # The stubs of the custom operations stay open gaps until a developer writes them.
    custom = {f"operations.{n}" for n, op in definition.operations.items() if op.kind == "custom"}
    assert {e.element_id for e in data if e.status == "gap"} == custom
    assert {e.status for e in data if e.element_id not in custom} == {"covered"}


def test_custom_ui_elements_get_the_shared_gap_files(result: GenerationResult) -> None:
    files = _files(result)
    kinds = {f.path: f.kind for f in result.files}
    for base in (
        "src/widgets/task-detail/ui/activity-tab",
        "src/widgets/overview/ui/workload-widget",
        "src/features/assign-task-form/ui/assignee-id-widget",
    ):
        assert kinds[base + ".gen.tsx"] == "generated"
        assert kinds[base + ".ext.tsx"] == "extension"
        name = base.rsplit("/", 1)[1]
        assert f'from "./{name}.ext";' in files[base + ".gen.tsx"]
        assert "TODO(appgen)" in files[base + ".ext.tsx"]
    rule = "src/features/assign-task-form/model/active-person-rule"
    assert kinds[rule + ".ext.ts"] == "extension"
    assert "return true;" in files[rule + ".ext.ts"]


def test_regeneration_keeps_the_extension_files(
    tmp_path: Path, definition: AppDefinition, result: GenerationResult
) -> None:
    write_result(result, tmp_path, "nextjs")
    paths = [
        tmp_path / "src/features/assign-task/api/assign-task.ext.ts",
        tmp_path / "src/widgets/task-detail/ui/activity-tab.ext.tsx",
    ]
    for path in paths:
        path.write_text(path.read_text().replace("TODO(appgen)", "Done by hand"))
    write_result(generate(definition, find_binding("nextjs")), tmp_path, "nextjs")
    for path in paths:
        assert "Done by hand" in path.read_text()


def test_the_app_has_a_dockerfile_and_a_compose_file(result: GenerationResult) -> None:
    files = _files(result)
    dockerfile = files["Dockerfile"]
    assert "# @trace app file" in dockerfile
    assert f"ARG NODE_IMAGE=node:{versions.NODE_VERSION}-alpine" in dockerfile
    assert "FROM ${NODE_IMAGE} AS base" in dockerfile
    install = "RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \\\n    pnpm install"
    assert install + " --store-dir /pnpm/store\n" in dockerfile
    assert "ENV NEXT_TELEMETRY_DISABLED=1 NEXT_OUTPUT=standalone" in dockerfile
    assert "RUN if [ ! -d drizzle ]; then pnpm db:generate; fi" in dockerfile
    assert "COPY --from=build --chown=node:node /app/drizzle ./drizzle" in dockerfile
    assert "USER node" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
    assert "node_modules\n.next\n" in files[".dockerignore"]
    compose = files["compose.yaml"]
    assert "# @trace app file" in compose
    assert "image: ${POSTGRES_IMAGE:-postgres:18-alpine}" in compose
    assert "DATABASE_URL: postgres://postgres:postgres@db:5432/project_tracker" in compose
    assert 'DATABASE_MIGRATE: "true"' in compose
    assert 'DATABASE_SEED: "true"' in compose
    assert "condition: service_healthy" in compose


def test_each_list_view_has_a_widget_and_its_page_shows_it(result: GenerationResult) -> None:
    files = _files(result)
    for name in ("project-table", "task-board", "task-table", "person-cards", "comment-table"):
        assert f"src/widgets/{name}/index.ts" in files
        assert f"src/widgets/{name}/ui/{name}-view.tsx" in files
    page = files["src/pages/projects/ui/projects-page.tsx"]
    assert '// @trace pages.projects file\n"use client";' in page
    assert 'import { ProjectTableView } from "@/widgets/project-table";' in page
    assert "<ProjectTableView /> {/* @trace pages.projects.content */}" in page
    assert '"@tanstack/react-table": "8.21.3"' in files["package.json"]
    assert '"react-hooks/incompatible-library": "off",' in files["eslint.config.mjs"]
    for path in ("data-table", "filters/date-range-filter", "values/avatar-value"):
        assert f"src/shared/ui/{path}.tsx" in files


def test_the_views_use_the_server_actions_of_the_entities(result: GenerationResult) -> None:
    files = _files(result)
    table = files["src/widgets/project-table/ui/project-table-view.tsx"]
    assert "personApi.list()," in table
    assert 'import { archiveProject } from "@/features/archive-project";' in table
    board = files["src/widgets/task-board/ui/task-board-view.tsx"]
    assert 'return updateTask(record.id, { status: value as Task["status"] });' in board
    assert "  updateTask,\n" in files["src/entities/task/index.ts"]


VIEWS = Path(__file__).parent / "fixtures" / "react-views.yaml"


def test_each_view_element_has_a_trace(nextjs: Binding, tmp_path: Path) -> None:
    definition = load_definition(VIEWS)
    result = generate(definition, nextjs)
    write_result(result, tmp_path, "nextjs")
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    status = {e.element_id: e.status for e in report.coverage.elements}
    for element in iter_elements(definition):
        if element.id.startswith("ui.views.") and element.kind not in ("sort", "grid"):
            assert status.get(element.id) in ("covered", "gap"), element.id


def test_the_app_shell_and_the_views_are_covered(
    definition: AppDefinition, result: GenerationResult, tmp_path: Path
) -> None:
    write_result(result, tmp_path, "nextjs")
    status = {e.element_id: e.status for e in check_traces(definition, tmp_path).coverage.elements}
    kinds = {"layout", "menu", "menu_item", "table_view", "board_view", "cards_view", "column"}
    for element in iter_elements(definition):
        if element.kind in kinds:
            assert status[element.id] == "covered", element.id


def test_each_detail_view_and_dashboard_has_a_widget_and_a_page(result: GenerationResult) -> None:
    files = _files(result)
    detail = files["src/widgets/task-detail/ui/task-detail-view.tsx"]
    assert "export function TaskDetailView({ id }: TaskDetailViewProps) {" in detail
    assert "resource.error instanceof NotFoundError" in detail
    assert "<CommentTableView where={(row) => row.taskId === record.id} />" in detail
    page = files["src/pages/task-detail/ui/task-detail-page.tsx"]
    assert '<TaskDetailView id={id ?? ""} /> {/* @trace pages.task_detail.content */}' in page
    dashboard = files["src/widgets/overview/ui/overview-dashboard.tsx"]
    assert "export function OverviewDashboard() {" in dashboard
    assert '<DashboardChart kind="donut"' in dashboard
    page = files["src/pages/dashboard/ui/dashboard-page.tsx"]
    assert "<OverviewDashboard /> {/* @trace pages.dashboard.content */}" in page
    assert "useParams" not in page
    for path in ("src/shared/lib/aggregate.ts", "src/shared/ui/widget-card.tsx"):
        assert path in files
    assert "src/shared/ui/dashboard-chart.tsx" in files


DETAILS = Path(__file__).parent / "fixtures" / "ui-details.yaml"


def test_the_details_and_the_dashboards_are_covered(nextjs: Binding, tmp_path: Path) -> None:
    definition = load_definition(DETAILS)
    write_result(generate(definition, nextjs), tmp_path, "nextjs")
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    status = {e.element_id: e.status for e in report.coverage.elements}
    kinds = {
        "detail_view",
        "detail_header",
        "detail_section",
        "detail_tab",
        "dashboard",
        "stat_widget",
        "chart_widget",
        "list_widget",
    }
    for element in iter_elements(definition):
        if element.kind in kinds:
            assert status[element.id] in ("covered", "gap"), element.id


def test_each_form_is_a_feature_that_calls_the_server_actions(result: GenerationResult) -> None:
    files = _files(result)
    form = files["src/features/new-project-form/ui/new-project-form.tsx"]
    assert "projectInputSchema.pick(" in form
    assert '"Enter a name."' in form
    assert "const found = submitErrors(error);" in form
    assert (
        "export function submitErrors(error: unknown): FormErrors {"
        in files["src/shared/lib/form.ts"]
    )
    assert "src/shared/ui/form-widgets/relation-select.tsx" in files
    detail = files["src/widgets/project-detail/ui/project-detail-view.tsx"]
    assert 'import { EditProjectFormDialog } from "@/features/edit-project-form";' in detail
    table = files["src/widgets/project-table/ui/project-table-view.tsx"]
    assert 'import { NewProjectFormDialog } from "@/features/new-project-form";' in table


FORMS = Path(__file__).parent / "fixtures" / "react-forms.yaml"


def test_a_page_form_and_the_form_elements_are_covered(nextjs: Binding, tmp_path: Path) -> None:
    definition = load_definition(FORMS)
    result = generate(definition, nextjs)
    write_result(result, tmp_path, "nextjs")
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    status = {e.element_id: e.status for e in report.coverage.elements}
    kinds = {"form", "form_section", "form_field", "form_on_success", "field_rules"}
    for element in iter_elements(definition):
        if element.kind in kinds or element.kind.endswith("_rule"):
            assert status[element.id] in ("covered", "gap"), element.id
    pages = [
        content
        for path, content in _files(result).items()
        if path.startswith("src/pages/") and "FormPage routeParams={params}" in content
    ]
    assert pages
    assert all("const params = useParams();" in page for page in pages)


def test_the_app_has_a_seed_with_the_mock_records(
    definition: AppDefinition, result: GenerationResult
) -> None:
    files = _files(result)
    package = json.loads(files["package.json"])
    assert package["scripts"]["db:seed"] == "tsx src/shared/db/run-seed.ts"
    assert "tsx" in package["devDependencies"]
    assert 'process.env.DATABASE_SEED === "true"' in files["instrumentation.ts"]
    assert "DATABASE_SEED=false" in files[".env.example"]
    assert '"server-only"' not in files["src/shared/db/connect.ts"]
    assert 'import { connect } from "./connect";' in files["src/shared/db/run-seed.ts"]
    data = files["src/shared/db/seed-data.ts"]
    records = mock_data(definition)
    for entity, rows in records.items():
        for record in rows:
            assert f'{{ id: "{record["id"]}"' in data, entity
    project = next(r for r in records["Project"] if r["name"] == "Meridian Portal")
    assert f'name: "Meridian Portal", key: "{project["key"]}"' in data
    seed = files["src/shared/db/seed.ts"]
    # The required foreign keys decide the order of the inserts.
    order = [seed.index(f"tx.insert({t}Table)") for t in ("person", "project", "task", "comment")]
    assert order == sorted(order)
    assert "tx.insert(projectMembersTable).values(seed.projectMembersSeed);" in seed
    # The optional foreign key of a task (its assignee) comes after all inserts.
    assert "for (const { id, ...values } of seed.taskSeedLinks)" in seed
    assert "assigneeId: null" in data


def test_the_seed_of_the_edge_cases_inserts_a_target_first(nextjs: Binding) -> None:
    files = _files(generate(load_definition(EDGE_CASES), nextjs))
    seed = files["src/shared/db/seed.ts"]
    # Owner has a required one_to_one foreign key to Profile.
    assert seed.index("tx.insert(profileTable)") < seed.index("tx.insert(ownerTable)")
    # Item refers to itself with an optional foreign key: a link.
    assert "seed.itemSeedLinks" in seed


def test_a_detail_page_for_an_unknown_id_is_not_found(result: GenerationResult) -> None:
    files = _files(result)
    route = files["app/(app-shell)/projects/[id]/page.tsx"]
    assert 'import { notFound } from "next/navigation";' in route
    assert 'export default async function Route({ params }: PageProps<"/projects/[id]">) {' in route
    assert "  const { id } = await params;" in route
    assert "if (!(await projectRepository.exists(id))) {\n    notFound();" in route
    assert "async exists(id: string): Promise<boolean> {" in files["src/shared/db/repository.ts"]
    # A list page needs no record.
    assert "notFound" not in files["app/(app-shell)/projects/page.tsx"]


def test_the_rules_of_an_entity_are_checks_and_constraints() -> None:
    definition = load_definition(Path(__file__).parent.parent / "examples/room-booking/app.yaml")
    files = {f.path: f.content for f in generate(definition, find_binding("nextjs")).files}
    repository = files["src/entities/booking/api/booking-repository.ts"]
    assert '      field: "endsAt",\n      op: "gt",\n      other: "startsAt",\n' in repository
    assert '      scope: ["roomId"],\n' in repository
    table = files["src/shared/db/schema/room.ts"]
    assert '  unique("uq_room_unique_name_per_floor").on(t.floor, t.name),\n' in table
