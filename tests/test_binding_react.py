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


def test_the_theme_comes_from_the_design_tokens(result: GenerationResult) -> None:
    files = _files(result)
    css = files["src/app/styles/index.css"]
    assert "--primary: oklch(0.511 0.262 276.966); /* @trace ui.tokens.color.primary */" in css
    dark = css.split(".dark {", 1)[1].split("}", 1)[0]
    assert "--primary: oklch(0.673 0.182 276.935); /* @trace ui.tokens.color.primary */" in dark
    assert "--spacing-4: 1rem; /* @trace ui.tokens.spacing.4 */" in css
    assert "--breakpoint-md: 768px; /* @trace ui.tokens.breakpoint.md */" in css
    providers = files["src/app/providers/index.tsx"]
    assert 'attribute="class"' in providers
    assert 'defaultTheme="system"' in providers
    assert "<ModeToggle />" in files["src/app/layout/root-layout.tsx"]
    assert 'setTheme("dark")' in files["src/features/toggle-theme/ui/mode-toggle.tsx"]


def test_an_app_without_a_mode_toggle_has_no_toggle(react: Binding) -> None:
    files = _files(
        generate(load_definition(EXAMPLE.parent.parent / "edge-cases" / "app.yaml"), react)
    )
    assert "src/features/toggle-theme/ui/mode-toggle.tsx" not in files
    assert "ModeToggle" not in files["src/app/layout/root-layout.tsx"]


def test_each_package_of_the_shadcn_components_has_a_version() -> None:
    names = shadcn.packages(shadcn.registry().values())
    assert sorted(set(names) - set(versions.COMPONENT_PACKAGES)) == []


def test_the_dockerfile_builds_with_pnpm_and_serves_with_nginx_as_non_root(
    result: GenerationResult,
) -> None:
    files = _files(result)
    dockerfile = files["Dockerfile"]
    assert dockerfile.startswith("# syntax=docker/dockerfile:1\n")
    assert "# @trace app file" in dockerfile
    install = "RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \\\n    pnpm install"
    assert install + " --store-dir /pnpm/store\n" in dockerfile
    assert "ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:" in dockerfile
    assert "FROM ${NODE_IMAGE} AS build" in dockerfile
    assert "USER nginx" in dockerfile
    assert "try_files $uri $uri/ /index.html;" in files["nginx.conf"]
    assert "node_modules" in files[".dockerignore"]


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


def test_the_router_puts_the_pages_in_their_layouts(result: GenerationResult) -> None:
    router = _files(result)["src/app/router.tsx"]

    assert 'import { AppShellLayout } from "@/widgets/layouts";' in router
    assert "<AppShellLayout>\n        <Outlet />" in router
    assert '{ path: "*", element: <NotFoundPage /> }' in router
    assert "RootLayout" not in router


def test_the_app_shell_follows_the_layout_definition(
    definition: AppDefinition, result: GenerationResult
) -> None:
    files = _files(result)
    shell = files["src/widgets/layouts/ui/app-shell-layout.tsx"]

    assert "export function AppShellLayout({ children }: { children: ReactNode })" in shell
    assert 'const belowMd = useMediaQuery("(width < 768px)");' in shell
    assert 'const mode: SidebarMode = belowMd ? "drawer" : belowLg ? "icons" : "expanded";' in shell
    assert '<Sidebar collapsible={mode === "icons" ? "icon" : "offcanvas"} side="left">' in shell
    assert "max-w-(--size-content) p-(--spacing-8) max-lg:p-(--spacing-6)" in shell
    assert '<div className="flex max-md:hidden">' not in shell
    assert '<div className="block max-md:hidden">\n          <PageSearch />' in shell
    assert "<MainMenu />" in shell
    assert "Project Tracker, generated by appgen." in shell
    # The column of the sidebar has its background, so it fills the height of a long page.
    assert (
        '"[&>[data-slot=sidebar]]:bg-sidebar [&>[data-slot=sidebar][data-side=left]]:border-r'
        in shell
    )
    layout = definition.ui.layouts["app_shell"]  # pyright: ignore[reportOptionalMemberAccess]
    for element in iter_elements(definition):
        if element.id.startswith(layout.id) and element.kind != "form_action":
            assert f"@trace {element.id}" in shell, element.id


def test_the_menu_has_the_items_groups_icons_and_active_route(
    definition: AppDefinition, result: GenerationResult
) -> None:
    menu = _files(result)["src/widgets/navigation/ui/main-menu.tsx"]

    assert (
        "import { ChevronRightIcon, FolderKanbanIcon, LayoutDashboardIcon, "
        'SquareKanbanIcon, UsersIcon } from "lucide-react";'
    ) in menu
    assert 'isActive={isActivePath(pageHref("taskBoard"), pathname)}' in menu
    assert '<span>{t("Task board")}</span>' in menu
    assert '<span>{t("Projects")}</span>' in menu
    assert '<Collapsible defaultOpen className="group/collapsible">' in menu
    for element in iter_elements(definition):
        if element.id.startswith("ui.navigation.main"):
            assert f"@trace {element.id}" in menu, element.id


def test_the_breadcrumbs_show_the_parent_pages_and_the_record(result: GenerationResult) -> None:
    files = _files(result)
    pages = files["src/shared/config/pages.ts"]
    labels = files["src/widgets/page-breadcrumbs/model/record-labels.ts"]

    assert 'parent: "projects",\n    recordEntity: "Project",\n    recordParam: "id",' in pages
    assert "parent: null,\n    recordEntity: null," in pages
    assert '"Project": {\n    load: async (id) => {' in labels
    assert '"Task": {\n    load: async (id) => {' in labels
    # The label loads again after a change of a record, for example an edit.
    assert "subscribe: (listener) => projectApi.subscribe(listener)," in labels
    crumbs = files["src/widgets/page-breadcrumbs/ui/page-breadcrumbs.tsx"]
    assert "source?.subscribe," in crumbs
    assert "export function PageSearch(" in files["src/features/search-pages/ui/page-search.tsx"]


LAYOUTS = Path(__file__).parent / "fixtures" / "react-layouts.yaml"


def test_layout_variants(react: Binding, tmp_path: Path) -> None:
    definition = load_definition(LAYOUTS)
    result = generate(definition, react)
    files = _files(result)

    library = files["src/widgets/layouts/ui/library-layout.tsx"]
    assert library.index("<SidebarInset") < library.index("{nav}")
    assert 'const nav = mode === "hidden" ? null : (' in library
    assert '<PageBreadcrumbs className="hidden max-lg:block min-w-0 overflow-hidden" />' in library
    assert "max-lg:[--shell-sidebar-width-icon:var(--size-rail)]" in library
    plain = files["src/widgets/layouts/ui/plain-layout.tsx"]
    assert "SidebarProvider" not in plain
    assert '<main className="flex flex-1 flex-col">{page}</main>' in plain
    assert "src/widgets/navigation/ui/unused-menu.tsx" not in files
    menu = files["src/widgets/navigation/ui/main-menu.tsx"]
    assert "<SidebarMenuSub>" in menu
    assert "SidebarGroupLabel" not in menu
    chapter = files["src/pages/chapter-detail/ui/chapter-detail-page.tsx"]
    assert "const { book_id: bookId, id } = useParams();" in chapter

    write_result(result, tmp_path, "react")
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    status = {e.element_id: e.status for e in report.coverage.elements}
    for element in iter_elements(definition):
        shell = element.kind in ("layout", "sidebar", "topbar", "content", "menu_item")
        if shell and not element.id.startswith("ui.navigation.unused"):
            assert status[element.id] == "covered", element.id


def test_each_list_view_has_a_widget_and_its_page_shows_it(result: GenerationResult) -> None:
    files = _files(result)
    for name in ("project-table", "task-board", "task-table", "person-cards", "comment-table"):
        assert f"src/widgets/{name}/index.ts" in files
        assert f"src/widgets/{name}/ui/{name}-view.tsx" in files
    page = files["src/pages/projects/ui/projects-page.tsx"]
    assert 'import { ProjectTableView } from "@/widgets/project-table";' in page
    assert "<ProjectTableView /> {/* @trace pages.projects.content */}" in page
    assert '"@tanstack/react-table": "8.21.3"' in files["package.json"]
    for path in ("data-table", "filters/date-range-filter", "values/avatar-value"):
        assert f"src/shared/ui/{path}.tsx" in files


def test_a_table_view_follows_its_definition(result: GenerationResult) -> None:
    table = _files(result)["src/widgets/project-table/ui/project-table-view.tsx"]
    assert "export function ProjectTableView({ where }: ProjectTableViewProps)" in table
    assert "personApi.list()," in table
    assert "{ // @trace ui.views.project_table.columns.name" in table
    assert 'meta: { width: "var(--size-column-lg)" },' in table
    assert 'meta: { className: "text-right max-md:hidden" },' in table
    assert "status: [], // @trace ui.views.project_table.filters.status" in table
    assert "const PAGE_SIZE = 20; // @trace ui.views.project_table.pagination" in table
    assert "const PAGE_SIZES: number[] = [10, 20, 50];" in table
    assert "return sortBy(rows, (row) => row.dueDate);" in table
    assert "onRowClick={(record) => run(rowActions.open, [record])}" in table
    assert 'confirmLabel: "Delete",' in table
    assert 'toast: "The project is deleted.", // @trace' in table
    assert "          selection\n" in table
    assert 'import { archiveProject } from "@/features/archive-project";' in table


def test_a_board_view_has_its_columns_and_moves_its_cards(result: GenerationResult) -> None:
    board = _files(result)["src/widgets/task-board/ui/task-board-view.tsx"]
    assert (
        '{ value: "in_progress", label: "In progress", color: "var(--status-progress)", '
        "limit: 8 }, // @trace ui.views.task_board.columns.in_progress"
    ) in board
    assert 'return updateTask(record.id, { status: value as Task["status"] });' in board
    assert '<DropdownMenuLabel>{t("Move to")}</DropdownMenuLabel>' in board
    assert (
        '<ViewLoading indicator="skeleton" shape="board" text={t("Loading the board")} />' in board
    )
    # The columns scroll in a scroll area with a horizontal scroll bar that always shows.
    assert '<ScrollArea type="always" className="w-full min-w-0' in board
    assert '<ScrollBar orientation="horizontal" />' in board
    assert "src/shared/ui/scroll-area.tsx" in _files(result)


VIEWS = Path(__file__).parent / "fixtures" / "react-views.yaml"


def test_the_view_features_have_traces_for_each_element(react: Binding, tmp_path: Path) -> None:
    definition = load_definition(VIEWS)
    result = generate(definition, react)
    files = _files(result)
    table = files["src/widgets/item-table/ui/item-table-view.tsx"]
    assert "function rowActionsFor(lookups: Lookups)" in table
    assert "const rowActions = rowActionsFor(lookups);" in table
    assert 'stage: ["new", "open"],' in table
    cards = files["src/widgets/member-cards/ui/member-cards-view.tsx"]
    assert '<div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">' in cards
    assert '<ViewLoading indicator="spinner" shape="cards" text="Loading" />' in cards

    write_result(result, tmp_path, "react")
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    status = {e.element_id: e.status for e in report.coverage.elements}
    for element in iter_elements(definition):
        if element.id.startswith("ui.views.") and element.kind not in ("sort", "grid"):
            assert status.get(element.id) in ("covered", "gap"), element.id


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
        if element.kind in ("entity", "field", "relation", "page", "token", "token_group") or (
            element.kind in ("layout", "menu", "menu_group", "menu_item", "layout_override")
        ):
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


def test_each_form_has_a_feature_slice_with_its_schema_and_rules(result: GenerationResult) -> None:
    files = _files(result)
    form = files["src/features/new-project-form/ui/new-project-form.tsx"]
    assert "const SCHEMA = projectInputSchema.pick({ name: true," in form
    assert (
        'errors.name ??= t("Enter a name."); '
        "// @trace ui.forms.new_project.fields.name.rules.required"
    ) in form
    assert '"zod": "4.6.7"' in files["package.json"]
    assert "export const projectInputSchema" in files["src/entities/project/model/schema.ts"]
    table = files["src/widgets/project-table/ui/project-table-view.tsx"]
    assert 'import { NewProjectFormDialog } from "@/features/new-project-form";' in table
    assert 'form: "edit_project",' in table


FORMS = Path(__file__).parent / "fixtures" / "react-forms.yaml"


def test_the_form_features_have_traces_for_each_element(react: Binding, tmp_path: Path) -> None:
    definition = load_definition(FORMS)
    result = generate(definition, react)
    files = _files(result)
    page = files["src/pages/new-book/ui/new-book-page.tsx"]
    assert "<NewBookFormPage routeParams={params} /> {/* @trace pages.new_book.content */}" in page
    new_book = files["src/features/new-book-form/ui/new-book-form.tsx"]
    assert 'compareRule(values.receivedAt, "gte", values.published)' in new_book
    shelf_book = files["src/features/shelf-book-form/ui/shelf-book-form.tsx"]
    assert 'shelfId: routeParams?.["shelf_id"] ?? null,' in shelf_book
    assert "SheetContent" in files["src/features/quick-edit-form/ui/quick-edit-form.tsx"]
    for widget in ("option-radio", "date-input", "date-time-input", "relation-select"):
        assert f"src/shared/ui/form-widgets/{widget}.tsx" in files

    write_result(result, tmp_path, "react")
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    status = {e.element_id: e.status for e in report.coverage.elements}
    for element in iter_elements(definition):
        if element.id.startswith("ui.forms."):
            assert status.get(element.id) in ("covered", "gap"), element.id


def test_the_pages_show_their_detail_views_and_dashboards(result: GenerationResult) -> None:
    files = _files(result)
    detail = files["src/pages/project-detail/ui/project-detail-page.tsx"]
    assert 'import { ProjectDetailView } from "@/widgets/project-detail";' in detail
    assert "const { id } = useParams();" in detail
    assert (
        '<ProjectDetailView id={id ?? ""} /> {/* @trace pages.project_detail.content */}' in detail
    )
    dashboard = files["src/pages/dashboard/ui/dashboard-page.tsx"]
    assert "<OverviewDashboard /> {/* @trace pages.dashboard.content */}" in dashboard
    assert "useParams" not in dashboard
    assert '"recharts": "3.10.1"' in files["package.json"]
    view = files["src/widgets/project-detail/ui/project-detail-view.tsx"]
    assert "EditProjectFormDialog" in view


DETAILS = Path(__file__).parent / "fixtures" / "ui-details.yaml"


def test_the_detail_and_dashboard_features_have_traces_for_each_element(
    react: Binding, tmp_path: Path
) -> None:
    definition = load_definition(DETAILS)
    result = generate(definition, react)
    write_result(result, tmp_path, "react")
    report = check_traces(definition, tmp_path)
    assert report.invalid == []
    status = {e.element_id: e.status for e in report.coverage.elements}
    for element in iter_elements(definition):
        if element.id.startswith(("ui.views.", "ui.dashboards.")):
            assert status.get(element.id) in ("covered", "gap"), element.id


def test_a_detail_page_has_one_main_heading(result: GenerationResult) -> None:
    files = _files(result)
    page = files["src/pages/project-detail/ui/project-detail-page.tsx"]
    assert '<PageHeader\n        title={t("Project")}\n        label\n' in page
    assert "        label\n" not in files["src/pages/projects/ui/projects-page.tsx"]
    view = files["src/widgets/project-detail/ui/project-detail-view.tsx"]
    assert '<h1 className="typography-heading">{String(record.name ?? "")}</h1>' in view
    header = files["src/widgets/page-header/ui/page-header.tsx"]
    assert '<p className="text-sm font-medium text-muted-foreground">{title}</p>' in header
