"""Helpers for the tests of the agent skill: its files, its front matter, and its code."""

import re
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parent.parent
SKILLS = ROOT / "src" / "appgen" / "skills"
SKILL = SKILLS / "appgen"

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
_SPAN = re.compile(r"`([^`]+)`")


def skill_docs() -> dict[str, str]:
    """Return the text of each Markdown file of the skill, by its path in the skill folder."""
    return {
        path.relative_to(SKILL).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(SKILL.rglob("*.md"))
    }


def front_matter(text: str) -> dict[str, Any]:
    """Return the YAML front matter of a SKILL.md file."""
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML front matter between '---' lines."
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return cast(dict[str, Any], data)


def code_texts(text: str) -> list[str]:
    """Return the code of a Markdown text: each line of the fenced blocks, and each code span.

    A code span that spans more than one line becomes one line.
    """
    lines = [line for block in _FENCE.findall(text) for line in block.splitlines()]
    prose = _FENCE.sub("", text)
    spans = [" ".join(span.split()) for span in _SPAN.findall(prose)]
    return [*lines, *spans]


def fenced_blocks(text: str, language: str) -> list[str]:
    """Return the content of the fenced code blocks of a language, for example `yaml`."""
    return re.findall(rf"^```{language}\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
