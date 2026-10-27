"""`scripts/check_plan.py` selects the sections of the app checks that a push must run.

The tests compare a copy of the repository with a changed copy: a section
runs only if its files or its generated apps changed.
"""

import importlib.util
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parent.parent
COPIED = ("src", "examples", "tests/fixtures", "scripts", "ui-tests/tests", "ui-tests/approved")
COPIED_FILES = (
    "uv.lock",
    "pyproject.toml",
    ".python-version",
    "ui-tests/package.json",
    "ui-tests/pnpm-lock.yaml",
    "ui-tests/playwright.config.ts",
    "ui-tests/tsconfig.json",
)


def load_plan() -> ModuleType:
    """Load `scripts/check_plan.py`: the folder `scripts` is not a package."""
    path = ROOT / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("check_plan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


plan = load_plan()


def copy_tree(target: Path) -> Path:
    """Copy the files that the plan reads into a folder."""
    ignore = shutil.ignore_patterns("node_modules", "__pycache__", "test-results", "expected")
    for folder in COPIED:
        shutil.copytree(ROOT / folder, target / folder, ignore=ignore)
    for file in COPIED_FILES:
        shutil.copy2(ROOT / file, target / file)
    return target


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return copy_tree(tmp_path_factory.mktemp("base"))


@pytest.fixture
def head(base: Path, tmp_path: Path) -> Path:
    shutil.copytree(base, tmp_path / "head")
    return tmp_path / "head"


def change(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, path
    path.write_text(text.replace(old, new, 1))


def names(check: str) -> set[str]:
    return {s.name for s in plan.SECTIONS if s.check == check}


@pytest.mark.parametrize("check", ["fastapi", "nextjs", "react", "react-api"])
def test_the_plan_has_each_section_of_a_check_script(check: str) -> None:
    text = (ROOT / "scripts" / f"check-{check}.sh").read_text()
    assert set(re.findall(r"(?m)^if section ([\w:.-]+); then$", text)) == names(check)


def test_the_plan_has_each_part_of_the_auth_ui_and_translation_checks() -> None:
    text = (ROOT / "scripts" / "check-auth-ui.sh").read_text()
    parts = dict(re.findall(r"(?m)^run_test ([\w-]+) (\w+\.py) ", text))
    assert parts == plan.AUTH_UI_TESTS
    assert f"for binding in {' '.join(plan.AUTH_UI_BINDINGS)}; do" in text
    expected = {f"auth-ui:{p}:{b}" for p in plan.AUTH_UI_TESTS for b in plan.AUTH_UI_BINDINGS}
    assert names("auth-ui") == expected
    text = (ROOT / "scripts" / "check-translations.sh").read_text()
    assert "for binding in react nextjs; do" in text
    assert names("translations") == {"translations:react", "translations:nextjs"}


def test_the_hook_can_start_each_check_of_the_plan() -> None:
    text = (ROOT / ".githooks" / "pre-push").read_text()
    (checks,) = re.findall(r'(?m)^ALL_APPS="([^"]+)"$', text)
    assert sorted(checks.split()) == sorted({s.check for s in plan.SECTIONS})


def test_the_files_of_the_sections_exist() -> None:
    assert len({s.name for s in plan.SECTIONS}) == len(plan.SECTIONS)
    for section in plan.SECTIONS:
        assert (ROOT / "scripts" / f"check-{section.check}.sh").is_file()
        for script in section.scripts:
            assert (ROOT / "scripts" / script).is_file(), script
        for app in section.apps:
            assert (ROOT / app.definition).is_file(), app
            assert app.extensions is None or (ROOT / app.extensions).is_dir(), app
        for path in section.ui:
            assert (ROOT / "ui-tests" / path).exists(), path


def test_a_section_reads_the_common_lines_and_its_own_lines_without_comments() -> None:
    text = (
        "# A comment.\n"
        "step() { echo; }\n"
        "if section a:one; then\n"
        "    run one\n"
        "    # Another comment.\n"
        "fi\n"
        "if section a:two; then\n"
        "    run two\n"
        "fi\n"
        "step end\n"
    )
    assert (
        plan.script_part(text, "a:one")
        == "step() { echo; }\nif section a:one; then\n    run one\nfi\nstep end\n"
    )
    assert "run one" not in plan.script_part(text, "a:two")


def test_the_closure_of_a_script_has_the_scripts_that_it_imports() -> None:
    closure = plan.script_closure(ROOT, ("auth_ui_test.py",))
    assert {"scripts/mock_oidc.py", "scripts/mock_smtp.py", "scripts/smoke_test.py"} <= set(closure)
    assert "scripts/files_test.ts" in plan.script_closure(ROOT, ("files_test.py",))


def test_no_section_runs_without_a_change(base: Path, head: Path) -> None:
    assert plan.changed_sections(head, base, {}) == {}


def test_a_changed_test_script_selects_its_sections(base: Path, head: Path) -> None:
    change(head / "scripts" / "totals_test.py", "import", "import os  # changed\nimport")
    assert set(plan.changed_sections(head, base, {})) == {"nextjs:totals"}


def test_a_changed_section_of_a_check_script_selects_only_it(base: Path, head: Path) -> None:
    script = head / "scripts" / "check-nextjs.sh"
    change(script, '    step "queries test"\n', '    step "queries test"\n    echo changed\n')
    change(script, "# Generate the project tracker", "# Generate the example project tracker")
    assert set(plan.changed_sections(head, base, {})) == {"nextjs:listings"}


def test_a_changed_common_line_of_a_check_script_selects_all_its_sections(
    base: Path, head: Path
) -> None:
    change(head / "scripts" / "check-react.sh", "set -eu\n", "set -eu\necho changed\n")
    assert set(plan.changed_sections(head, base, {})) == names("react")


def test_a_changed_screenshot_selects_the_ui_sections_of_its_binding(
    base: Path, head: Path
) -> None:
    screenshot = next((head / "ui-tests" / "approved" / "react" / "light").iterdir())
    screenshot.write_bytes(screenshot.read_bytes() + b"\0")
    assert set(plan.changed_sections(head, base, {})) == {"react:project-tracker"}


def test_a_changed_ui_test_selects_the_sections_that_run_it(base: Path, head: Path) -> None:
    change(head / "ui-tests" / "tests" / "listings.spec.ts", "import", "// Changed.\nimport")
    assert set(plan.changed_sections(head, base, {})) == {
        "nextjs:project-tracker",
        "react:project-tracker",
        "auth-ui:listings:react",
        "auth-ui:listings:nextjs",
        "auth-ui:listings:react-api",
    }


def test_a_changed_fixture_selects_the_sections_of_its_apps(
    base: Path, head: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sections = tuple(
        s for s in plan.SECTIONS if s.name in {"react:totals", "react:invoices", "nextjs:totals"}
    )
    monkeypatch.setattr(plan, "SECTIONS", sections)
    change(head / "tests" / "fixtures" / "totals.yaml", "title: ", "title: Changed ")
    reasons = plan.changed_sections(head, base, {})
    assert set(reasons) == {"react:totals", "nextjs:totals"}
    assert "tests/fixtures/totals.yaml" in reasons["react:totals"]


def test_the_hash_of_an_app_changes_with_its_keys() -> None:
    totals = plan.App("tests/fixtures/totals.yaml", "react")
    api = plan.App("tests/fixtures/totals.yaml", "react", keys=(("x-react-data", "api"),))
    missing = plan.App("tests/fixtures/missing.yaml", "react")
    hashes = plan.app_hashes(ROOT, [totals, api, missing])
    assert hashes[totals] is not None and hashes[api] is not None
    assert hashes[totals] != hashes[api]
    assert hashes[missing] is None
    assert plan.app_hashes(ROOT, [totals]) == {totals: hashes[totals]}


def test_the_hash_of_an_app_changes_with_its_replacements() -> None:
    rooms = plan.App(plan.ROOMS, "fastapi")
    ses = plan.App(plan.ROOMS, "fastapi", replace=plan.SES)
    wrong = plan.App(plan.ROOMS, "fastapi", replace=(("  delivery: none\n", "  delivery: ses\n"),))
    hashes = plan.app_hashes(ROOT, [rooms, ses, wrong])
    assert hashes[rooms] is not None and hashes[ses] is not None
    assert hashes[rooms] != hashes[ses]
    assert hashes[wrong] is None


def test_record_keeps_the_sections_of_the_passed_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPGEN_CHECK_CACHE", str(tmp_path / "cache"))
    state = tmp_path / "state"
    state.write_text("nextjs:totals abc\nreact:totals def\nauth-ui:places:react ghi\n")
    sections = tmp_path / "sections"
    sections.write_text("nextjs:totals\n")
    assert plan.record_command(state, ["react"], sections) == 0
    assert plan.passed_sections() == {"react:totals def", "nextjs:totals abc"}
    assert plan.record_command(state, ["auth-ui"]) == 0
    assert plan.passed_sections() == {
        "react:totals def",
        "nextjs:totals abc",
        "auth-ui:places:react ghi",
    }
