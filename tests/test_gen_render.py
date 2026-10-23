import os
from dataclasses import replace
from pathlib import Path

import pytest

from appgen.dsl import AppDefinition, load_definition
from appgen.gen import Binding, GenerationError, Output, find_binding, generate
from appgen.gen.render import normalize_content, normalize_path

TESTS = Path(__file__).parent
GOLDEN = TESTS / "golden" / "minimal"


@pytest.fixture
def definition() -> AppDefinition:
    return load_definition(TESTS / "fixtures" / "project-tracker.yaml")


@pytest.fixture
def minimal() -> Binding:
    return find_binding("minimal")


def _binding(tmp_path: Path, templates: dict[str, str], outputs: tuple[Output, ...]) -> Binding:
    for name, text in templates.items():
        (tmp_path / name).write_text(text, newline="")
    return Binding(
        name="temp",
        description="A binding for one test.",
        template_dir=tmp_path,
        outputs=outputs,
        covers=frozenset({"app", "entity"}),
    )


def test_output_matches_the_golden_files(definition: AppDefinition, minimal: Binding) -> None:
    files = {f.path: f.content for f in generate(definition, minimal).files}
    if os.environ.get("APPGEN_UPDATE_GOLDEN") == "1":
        for path, content in files.items():
            target = GOLDEN / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode())
    golden = {
        path.relative_to(GOLDEN).as_posix(): path.read_bytes().decode()
        for path in sorted(GOLDEN.rglob("*"))
        if path.is_file()
    }
    assert files == golden


def test_two_runs_give_the_same_output(definition: AppDefinition, minimal: Binding) -> None:
    assert generate(definition, minimal) == generate(definition, minimal)


def test_files_are_sorted_by_path(definition: AppDefinition, minimal: Binding) -> None:
    reverse = replace(minimal, outputs=tuple(reversed(minimal.outputs)))
    paths = [f.path for f in generate(definition, reverse).files]
    assert paths == sorted(paths)


def test_a_missing_value_stops_the_run(tmp_path: Path, definition: AppDefinition) -> None:
    binding = _binding(
        tmp_path, {"t.j2": "{{ element.no_such_key }}"}, (Output("t.j2", "x/{{ name }}", "entity"),)
    )
    with pytest.raises(GenerationError, match=r"'t\.j2' for 'entities\.Project'"):
        generate(definition, binding)


def test_a_missing_variable_stops_the_run(tmp_path: Path, definition: AppDefinition) -> None:
    binding = _binding(tmp_path, {"t.j2": "{{ nothing }}"}, (Output("t.j2", "x.txt"),))
    with pytest.raises(GenerationError, match="'nothing' is undefined"):
        generate(definition, binding)


def test_output_has_lf_and_one_final_newline(tmp_path: Path, definition: AppDefinition) -> None:
    binding = _binding(tmp_path, {"t.j2": "a\r\nb\rc\n\n\n"}, (Output("t.j2", "x.txt"),))
    assert generate(definition, binding).files[0].content == "a\nb\nc\n"


def test_two_rules_cannot_write_the_same_path(tmp_path: Path, definition: AppDefinition) -> None:
    binding = _binding(tmp_path, {"t.j2": "x"}, (Output("t.j2", "x.txt"), Output("t.j2", "x.txt")))
    with pytest.raises(GenerationError, match="Two output rules"):
        generate(definition, binding)


@pytest.mark.parametrize(
    ("text", "expected"), [("", "\n"), ("x", "x\n"), ("x\r\n", "x\n"), ("\n\n", "\n")]
)
def test_normalize_content(text: str, expected: str) -> None:
    assert normalize_content(text) == expected


def test_normalize_path() -> None:
    assert normalize_path("a\\b/./c.txt") == "a/b/c.txt"
    for bad in ["", "/etc/passwd", "../x", "a/../../x"]:
        with pytest.raises(GenerationError):
            normalize_path(bad)
