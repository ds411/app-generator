"""Tests of the user docs: the examples are valid, and the links work."""

import re
from pathlib import Path

import pytest

from appgen.dsl import load_definition_text

ROOT = Path(__file__).parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def _yaml_blocks(text: str) -> list[str]:
    return re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)


def test_the_complete_definitions_in_the_dsl_reference_are_valid() -> None:
    blocks = [b for b in _yaml_blocks((ROOT / "docs" / "dsl.md").read_text()) if "version: 0" in b]
    assert blocks
    for block in blocks:
        load_definition_text(block, "docs/dsl.md")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_the_local_links_of_the_docs_exist(doc: Path) -> None:
    for target in _LINK.findall(doc.read_text()):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        assert (doc.parent / target).exists(), f"{doc.name}: {target}"
