"""The skill tells an agent how to write a new definition, with the DSL and the codes (ADR 0015).

The DSL reference of the skill is made from docs/dsl.md, the sections
table names each section of the DSL, and the diagnostics reference names
each code of the validator and of the trace checker, and no other.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from skill_support import ROOT, SKILL, fenced_blocks, skill_docs
from typer.testing import CliRunner

from appgen.cli import app
from appgen.dsl import check_file
from appgen.dsl.schema import json_schema
from appgen.gen import find_binding, generate, write_result
from appgen.trace import check_traces

SOURCE = ROOT / "src" / "appgen"
NEW_DEFINITION = SKILL / "references" / "new-definition.md"
DIAGNOSTICS = SKILL / "references" / "diagnostics.md"
SCHEMA_LINE = (
    "# yaml-language-server: $schema="
    "https://raw.githubusercontent.com/ds411/app-generator/main/schema/app.schema.json"
)
_CODE = re.compile(r"[a-z]+(?:-[a-z]+)+")
_ROW_CODE = re.compile(r"^\| `([a-z-]+)`", re.MULTILINE)


def source_codes() -> dict[str, set[str]]:
    """Return the diagnostic codes in the source: of a definition, and of a trace check.

    A code is a string constant that is the `code` argument of a call, the
    first argument of a `_error` call or of a `Diagnostic`, or the second
    argument of `TraceProblem.of`.
    """
    codes: dict[str, set[str]] = {"definition": set(), "trace": set()}
    for path in sorted(SOURCE.rglob("*.py")):
        part = "trace" if path.parent.name == "trace" else "definition"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                codes[part].update(_call_codes(node))
    return codes


def _call_codes(call: ast.Call) -> set[str]:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    values = [k.value for k in call.keywords if k.arg == "code"]
    if name in {"_error", "Diagnostic"} and call.args:
        values.append(call.args[0])
    if name == "of" and len(call.args) > 1:
        values.append(call.args[1])
    # A code can be a conditional expression of two codes.
    return {
        node.value
        for value in values
        for node in ast.walk(value)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _CODE.fullmatch(node.value)
    }


def reference_codes() -> dict[str, set[str]]:
    """Return the codes in the first column of each table of the diagnostics reference."""
    text = DIAGNOSTICS.read_text(encoding="utf-8")
    definition, trace = text.split("## Problems of a trace check")
    return {
        "definition": set(_ROW_CODE.findall(definition)),
        "trace": set(_ROW_CODE.findall(trace)),
    }


def test_the_dsl_reference_of_the_skill_is_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "update_skill_references.py"), "--check"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_the_dsl_reference_of_the_skill_has_no_links_into_the_repository() -> None:
    text = (SKILL / "references" / "dsl.md").read_text(encoding="utf-8")

    assert text.startswith("<!-- Made from docs/dsl.md")
    assert "](adr/" not in text
    assert "](traces.md" not in text
    assert "](https://github.com/ds411/app-generator/blob/main/docs/adr/0002-" in text


def test_the_source_has_the_codes_of_the_examples() -> None:
    # The collector of the codes finds each code of the broken examples.
    codes = source_codes()
    for path in sorted((ROOT / "examples" / "invalid").glob("*.yaml")):
        match = re.match(r"# expect: ([a-z-]+)", path.read_text(encoding="utf-8"))
        assert match
        assert match.group(1) in codes["definition"]
    assert {"unknown-element", "skipped-trace", "gap-to-close"} <= codes["trace"]


@pytest.mark.parametrize("part", ["definition", "trace"])
def test_the_diagnostics_reference_has_each_code_and_no_other(part: str) -> None:
    in_source = source_codes()[part]
    in_reference = reference_codes()[part]

    assert sorted(in_source - in_reference) == [], "Add these codes to diagnostics.md."
    assert sorted(in_reference - in_source) == [], "These codes of diagnostics.md do not exist."


def test_the_sections_table_has_each_section_of_the_dsl() -> None:
    text = NEW_DEFINITION.read_text(encoding="utf-8")
    table = text.split("## Sections\n", 1)[1].split("\n## ", 1)[0]

    sections = set(_ROW_CODE.findall(table))

    assert sections == set(json_schema()["properties"])


def test_each_complete_definition_of_the_skill_is_valid(tmp_path: Path) -> None:
    runner = CliRunner()
    count = 0
    for name, text in skill_docs().items():
        for number, block in enumerate(fenced_blocks(text, "yaml")):
            yaml.safe_load(block)
            if not re.search(r"^version: 0$", block, re.MULTILINE):
                continue
            path = tmp_path / f"{name.replace('/', '-')}-{number}.yaml"
            path.write_text(block, encoding="utf-8")
            result = runner.invoke(app, ["validate", str(path), "--format", "json"])
            assert result.exit_code == 0, f"{name}, YAML block {number}:\n{result.output}"
            count += 1
    assert count >= 2


@pytest.fixture(scope="module")
def start_definition(tmp_path_factory: pytest.TempPathFactory) -> Path:
    (block,) = [b for b in fenced_blocks(NEW_DEFINITION.read_text(), "yaml") if "version: 0" in b]
    path = tmp_path_factory.mktemp("start") / "app.yaml"
    path.write_text(block, encoding="utf-8")
    return path


def test_the_start_definition_has_the_schema_line(start_definition: Path) -> None:
    assert start_definition.read_text(encoding="utf-8").splitlines()[0] == SCHEMA_LINE
    assert SCHEMA_LINE in (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "stable names" in NEW_DEFINITION.read_text(encoding="utf-8")


@pytest.mark.parametrize("binding_name", ["nextjs", "react", "fastapi"])
def test_the_start_definition_generates_and_passes_the_check(
    start_definition: Path, binding_name: str, tmp_path: Path
) -> None:
    definition, diagnostics = check_file(start_definition)
    assert definition is not None
    assert diagnostics == []
    binding = find_binding(binding_name)

    write_result(generate(definition, binding), tmp_path, binding.name)
    report = check_traces(definition, tmp_path)

    assert report.exit_code == 0
    assert [gap.element_id for gap in report.coverage.gaps] == ["operations.cancel_booking"]
