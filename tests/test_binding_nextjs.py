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
from appgen.dsl import AppDefinition, load_definition, load_definition_text
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
