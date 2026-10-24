"""The skill names each kind of extension file of each binding (ADR 0015).

The reference `fill-gaps.md` has one section for each binding, with the
path pattern of each kind of extension file, for example
`src/features/<operation>/api/<operation>.ext.ts`. The tests generate the
examples and a fixture with each kind of custom element, and compare
the extension files of the output with the patterns.
"""

import re
from functools import cache
from pathlib import Path

import pytest
from skill_support import ROOT, SKILL, code_texts

from appgen.dsl import load_definition
from appgen.gen import find_binding, generate

FILL_GAPS = SKILL / "references" / "fill-gaps.md"
SECTIONS = {"nextjs": "Next.js", "react": "React", "fastapi": "FastAPI"}
DEFINITIONS = [
    *sorted((ROOT / "examples").glob("*/app.yaml")),
    ROOT / "tests" / "fixtures" / "react-gaps.yaml",
]
TEST_COMMANDS = {
    "nextjs": ["pnpm lint", "pnpm typecheck", "pnpm build"],
    "react": ["pnpm lint", "pnpm typecheck", "pnpm build"],
    "fastapi": ["uv run ruff check", "uv run pyright", "uv run pytest"],
}


def section(binding: str) -> str:
    """Return the text of the section of a binding in fill-gaps.md."""
    text = FILL_GAPS.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    (found,) = [p for p in parts if p.startswith(SECTIONS[binding] + "\n")]
    return found


def patterns(binding: str) -> dict[str, re.Pattern[str]]:
    """Return the path patterns of the extension files in the table of the section of a binding."""
    rows = "\n".join(line for line in section(binding).splitlines() if line.startswith("| "))
    paths = [c for c in code_texts(rows) if re.fullmatch(r"[^ ]+/[^ ]+\.(ts|tsx|py)", c)]
    return {path: re.compile(re.sub(r"<[^>]+>", "[^/]+", re.escape(path))) for path in paths}


@cache
def extension_files(binding: str) -> dict[str, str]:
    """Return the extension files of the definitions with a binding, by path, with their source."""
    found: dict[str, str] = {}
    for path in DEFINITIONS:
        result = generate(load_definition(path), find_binding(binding))
        for file in result.files:
            if file.kind == "extension":
                found.setdefault(file.path, path.relative_to(ROOT).as_posix())
    return found


@pytest.mark.parametrize("binding", sorted(SECTIONS))
def test_each_kind_of_extension_file_is_in_the_reference(binding: str) -> None:
    known = patterns(binding)
    missing = [
        f"{path} (from {source})"
        for path, source in sorted(extension_files(binding).items())
        if not any(p.fullmatch(path) for p in known.values())
    ]

    assert missing == [], f"Add these kinds of extension files to fill-gaps.md: {missing}"


@pytest.mark.parametrize("binding", sorted(SECTIONS))
def test_each_pattern_of_the_reference_matches_an_extension_file(binding: str) -> None:
    files = extension_files(binding)

    unused = [text for text, p in patterns(binding).items() if not any(map(p.fullmatch, files))]

    assert unused == []


@pytest.mark.parametrize("binding", sorted(SECTIONS))
def test_the_section_of_a_binding_gives_the_test_commands_and_the_stub_markers(
    binding: str,
) -> None:
    text = section(binding)

    for command in TEST_COMMANDS[binding]:
        assert f"`{command}`" in text or f"{command}`" in text
    reference = FILL_GAPS.read_text(encoding="utf-8")
    for marker in find_binding(binding).stub_markers:
        assert marker in reference


def test_the_reference_tells_to_write_code_only_in_extension_files() -> None:
    text = FILL_GAPS.read_text(encoding="utf-8")

    assert "Write code only in extension files" in text
    assert "change the definition" in text
    assert "`@trace:manual <element ID> file`" in text


def test_the_fixture_has_each_kind_of_custom_element() -> None:
    kinds = {
        Path(path).name.split(".")[0].rsplit("-", 1)[-1]
        for path in extension_files("react")
        if path.endswith((".ext.ts", ".ext.tsx"))
    }

    assert {"content", "tab", "section", "widget", "rule", "action"} <= kinds
