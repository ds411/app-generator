from pathlib import Path

import pytest

from appgen.dsl import AppDefinition, load_definition
from appgen.trace import ScanResult, find_invalid_traces, scan_folder, valid_traces

TESTS = Path(__file__).parent


@pytest.fixture
def definition() -> AppDefinition:
    return load_definition(TESTS / "fixtures" / "project-tracker.yaml")


def _scan(root: Path, files: dict[str, str]) -> ScanResult:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return scan_folder(root)


def test_valid_traces_give_no_problems(definition: AppDefinition, tmp_path: Path) -> None:
    scan = _scan(tmp_path, {"a.py": "# @trace app file\nx = 1  # @trace entities.Task\n"})

    assert find_invalid_traces(definition, scan) == []


def test_lists_malformed_traces(definition: AppDefinition, tmp_path: Path) -> None:
    scan = _scan(tmp_path, {"a.py": "# @trace:todo app\n# @trace app begin\n"})

    problems = find_invalid_traces(definition, scan)

    assert [(p.file, p.line, p.code, p.text) for p in problems] == [
        ("a.py", 1, "unknown-kind", "@trace:todo app"),
        ("a.py", 2, "unclosed-block", "@trace app begin"),
    ]


def test_lists_traces_to_unknown_elements_with_a_hint(
    definition: AppDefinition, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        {
            "b.ts": "x; // @trace entities.Task.fields.titel\n",
            "a.ts": "// @trace:manual zzz file\n",
        },
    )

    problems = find_invalid_traces(definition, scan)

    assert [(p.file, p.line, p.code, p.text, p.hint) for p in problems] == [
        ("a.ts", 1, "unknown-element", "@trace:manual zzz file", None),
        (
            "b.ts",
            1,
            "unknown-element",
            "@trace entities.Task.fields.titel",
            "Did you mean 'entities.Task.fields.title'?",
        ),
    ]
    assert str(problems[1]) == (
        "b.ts:1:7: error[unknown-element]: The definition has no element "
        "'entities.Task.fields.titel'.\n"
        "  hint: Did you mean 'entities.Task.fields.title'?"
    )


def test_lists_generated_traces_outside_the_generated_files(
    definition: AppDefinition, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        {
            "gen.py": "# @trace app file\n",
            "ext.py": "# @trace app file\n# @trace:manual pages.projects\n",
        },
    )

    problems = find_invalid_traces(definition, scan, generated_files={"gen.py"})

    assert [(p.file, p.line, p.code) for p in problems] == [
        ("ext.py", 1, "generated-trace-in-manual-file")
    ]


def test_valid_traces_leave_out_invalid_traces(definition: AppDefinition, tmp_path: Path) -> None:
    scan = _scan(tmp_path, {"a.py": "# @trace app file\n# @trace nothing\nx = 1\n"})

    problems = find_invalid_traces(definition, scan)

    assert [t.element_id for t in valid_traces(scan, problems)] == ["app"]
