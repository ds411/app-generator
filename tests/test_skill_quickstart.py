"""The quick-start skill agrees with the DSL and the bindings (ADR 0053).

The table of defaults names keys of the definition, values of these
keys, and bindings. Each key and each value exists in the JSON Schema of
the DSL or in the extension keys of a binding, and each binding is in
the registry of the bindings. Thus a change of the DSL fails these tests
until the skill agrees. Each YAML example of the skill validates, and
its record of the defaults has the format of the skill.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import jsonschema
import pydantic
import pytest
import yaml
from skill_support import QUICKSTART, fenced_blocks, front_matter, skill_docs
from typer.testing import CliRunner

from appgen.cli import app
from appgen.dsl.schema import json_schema
from appgen.gen import find_binding
from appgen.gen.binding import ExtensionKey
from appgen.gen.registry import available_bindings

SKILL_MD = QUICKSTART / "SKILL.md"
SCHEMA = json_schema()
DEFS: dict[str, Any] = SCHEMA["$defs"]

_SPAN = re.compile(r"`([^`]+)`")
_PATH = re.compile(r"[a-z][a-z_]*(?:\.(?:<[^<>.]+>|[a-z_][a-z0-9_-]*))*")
RECORD_START = "# appgen-quickstart defaults:"
RECORD_LINE = re.compile(r'# - (?P<row>[a-z_]+): (?P<choice>.+)\. Prompt: "(?P<words>[^"]+)"')
"""A line of the record of the defaults at the top of `app.yaml`."""

KINDS = {"app": "app", "entities.<>": "entity", "entities.<>.fields.<>": "field"}
"""The element kind of a parent of an extension key, with `<>` for each name."""

NO_DEFAULT = {
    "version": "A definition always has `version: 0`.",
    "operations": "The CRUD shorthand gives the operations, and the logic of the prompts "
    "gives a custom operation (the steps).",
    "webhooks": "An outside service sends its events only after a person sets it up.",
}
"""The sections of the DSL that the table of defaults does not name, and the reason."""


@dataclass(frozen=True)
class Row:
    """A row of a table of the skill."""

    line: int
    cells: list[str]

    def spans(self, column: int) -> list[str]:
        return _SPAN.findall(self.cells[column])


def table(heading: str) -> list[Row]:
    """Return the rows of the table under a `##` heading of SKILL.md, without the header."""
    lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"## {heading}")
    rows: list[Row] = []
    for number, line in enumerate(lines[start + 1 :], start + 2):
        if line.startswith("## "):
            break
        if line.startswith("|"):
            rows.append(Row(number, [cell.strip() for cell in line.strip("|").split(" | ")]))
    assert rows, f"SKILL.md has no table under '## {heading}'."
    return rows[2:]


def expand(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the schemas that a node of the JSON Schema can be: the references and the unions."""
    if "$ref" in node:
        return expand(DEFS[node["$ref"].removeprefix("#/$defs/")])
    for key in ("anyOf", "oneOf", "allOf"):
        if key in node:
            return [n for sub in node[key] for n in expand(sub)]
    return [node]


def children(node: dict[str, Any], segment: str) -> list[dict[str, Any]]:
    """Return the schemas of a key of a node. `<...>` is a name of a mapping."""
    found: list[dict[str, Any]] = []
    for option in expand(node):
        if segment.startswith("<"):
            extra = option.get("additionalProperties")
            if isinstance(extra, dict):
                found.append(cast(dict[str, Any], extra))
            patterns = cast(dict[str, Any], option.get("patternProperties", {}))
            found.extend(sub for pattern, sub in patterns.items() if pattern != "^x-")
        elif segment in option.get("properties", {}):
            found.append(option["properties"][segment])
    return found


def extension_keys() -> dict[str, list[ExtensionKey]]:
    """Return the extension keys of the registered bindings, by their names."""
    keys: dict[str, list[ExtensionKey]] = {}
    for name in available_bindings():
        for key in find_binding(name).extension_keys:
            keys.setdefault(key.name, []).append(key)
    return keys


def key_errors(span: str) -> list[str]:
    """Check a key of the table, with an optional value: `<path>` or `<path>: <value>`."""
    path, _, text = span.partition(": ")
    if not _PATH.fullmatch(path):
        return [f"'{span}' is not a key of the definition"]
    segments = path.split(".")
    nodes: list[dict[str, Any]] = [SCHEMA]
    for index, segment in enumerate(segments):
        if segment.startswith("x-"):
            parent = ".".join("<>" if s.startswith("<") else s for s in segments[:index])
            return _extension_errors(span, segment, KINDS.get(parent), text)
        nodes = [child for node in nodes for child in children(node, segment)]
        if not nodes:
            return [f"'{span}': the DSL has no key '{'.'.join(segments[: index + 1])}'"]
    if not text or "<" in text:
        return []
    value: Any = yaml.safe_load(text)
    for node in nodes:
        validator = jsonschema.Draft202012Validator({"$defs": DEFS, **node})
        if validator.is_valid(value):  # pyright: ignore[reportUnknownMemberType]
            return []
    return [f"'{span}': the DSL does not accept the value {value!r}"]


def _extension_errors(span: str, name: str, kind: str | None, text: str) -> list[str]:
    if kind is None:
        return [f"'{span}': add the element kind of the parent of '{name}' to KINDS"]
    keys = [key for key in extension_keys().get(name, []) if kind in key.kinds]
    if not keys:
        return [f"'{span}': no binding has the extension key '{name}' on the kind '{kind}'"]
    if not text:
        return []
    value = yaml.safe_load(text)
    for key in keys:
        try:
            pydantic.TypeAdapter(key.type).validate_python(value)
        except pydantic.ValidationError:
            continue
        return []
    return [f"'{span}': the extension key '{name}' does not accept the value {value!r}"]


def record_rows(text: str) -> list[str]:
    """Return the rows of the record of the defaults at the top of a definition."""
    lines = text.splitlines()
    start = lines.index(RECORD_START)
    rows: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("# - "):
            break
        match = RECORD_LINE.fullmatch(line)
        assert match, f"The line of the record does not have the format of the skill: {line}"
        rows.append(match.group("row"))
    return rows


def test_the_description_leaves_the_other_tasks_to_the_skill_appgen() -> None:
    description = front_matter(SKILL_MD.read_text(encoding="utf-8"))["description"]

    for words in (
        "Make a working app from one or more prompts",
        "asks no question about a default",
        "records the defaults at the top of app.yaml",
        "a new app from a description",
        "a later prompt of the same session changes a default",
        "use the appgen skill",
    ):
        assert words in description


def test_the_skill_uses_the_skill_appgen_for_the_cli_and_the_dsl() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "`/appgen` in Claude Code" in text
    assert "[../appgen/SKILL.md](../appgen/SKILL.md)" in text
    # The details stay in the skill appgen: the quick start has only SKILL.md.
    assert list(skill_docs(QUICKSTART)) == ["SKILL.md"]


def test_each_binding_of_the_table_exists() -> None:
    bindings = set(available_bindings()) - {"minimal"}
    errors: list[str] = []
    for row in table("Bindings"):
        names = row.spans(1)
        if not names:
            errors.append(f"SKILL.md:{row.line}: the row names no binding")
        errors.extend(
            f"SKILL.md:{row.line}: the binding '{n}' does not exist"
            for n in names
            if n not in bindings
        )
    assert errors == []


@pytest.mark.parametrize(("heading", "column"), [("Bindings", 2), ("Defaults", 2)])
def test_each_key_and_value_of_the_table_exists(heading: str, column: int) -> None:
    errors = [
        f"SKILL.md:{row.line}: {error}"
        for row in table(heading)
        for span in row.spans(column)
        for error in key_errors(span)
    ]

    assert errors == []


@pytest.mark.parametrize(
    "span",
    [
        "auth.passwords",
        "auth.providers.<provider>.issuers",
        "auth.delivery: pigeon",
        "app.x-react-data: graphql",
        "app.x-fastapi-unknown",
        "entities.<Entity>.fields.<field>.type: picture",
    ],
)
def test_the_key_check_finds_a_key_or_a_value_that_does_not_exist(span: str) -> None:
    assert key_errors(span) != []


def test_the_key_check_reads_the_names_the_unions_and_the_extension_keys() -> None:
    for span in (
        "entities.<Entity>.fields.<field>.type: point",
        'access.roles.<role>.operations: ["*"]',
        "auth.providers.<provider>.issuer: https://cognito-idp.<region>.amazonaws.com/<pool>",
        "app.x-react-data: api",
        "entities.<Entity>.x-mock-count: 3",
    ):
        assert key_errors(span) == [], span


def test_the_bindings_table_has_the_rows_of_the_story() -> None:
    rows = {(tuple(row.spans(1)), tuple(row.spans(2))) for row in table("Bindings")}

    assert (("nextjs",), ()) in rows
    assert (("fastapi",), ()) in rows
    assert (("react", "fastapi"), ("app.x-react-data: api",)) in rows
    assert (("react",), ("app.x-react-data: mock",)) in rows
    # The first row is the default: a prompt that names no stack.
    assert table("Bindings")[0].cells[0].startswith("No stack.")


def test_the_defaults_table_has_a_row_for_each_section_of_the_dsl() -> None:
    rows = table("Defaults")
    names = [span for row in rows for span in row.spans(0)]
    sections = {span.split(".")[0] for row in rows for span in row.spans(2)}

    assert len(names) == len(set(names)) == len(rows)
    assert {
        "app",
        "auth",
        "access",
        "sign_up",
        "providers",
        "translations",
        "seed",
        "apis",
        "jobs",
        "notifications",
        "workflows",
    } <= set(names)
    assert "binding" not in names
    assert sorted(set(SCHEMA["properties"]) - sections - set(NO_DEFAULT)) == [], (
        "Give the new sections of the DSL a row of the table of defaults, or add them to "
        "NO_DEFAULT with a reason."
    )
    assert sorted(set(NO_DEFAULT) & sections) == []


def test_each_yaml_example_of_the_skill_is_valid(tmp_path: Path) -> None:
    blocks = fenced_blocks(SKILL_MD.read_text(encoding="utf-8"), "yaml")
    runner = CliRunner()

    assert blocks
    for number, block in enumerate(blocks):
        path = tmp_path / f"example-{number}.yaml"
        path.write_text(block, encoding="utf-8")
        result = runner.invoke(app, ["validate", str(path), "--format", "json"])
        assert result.exit_code == 0, f"YAML block {number}:\n{result.output}"


def test_the_record_of_the_example_names_rows_of_the_tables() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    (block,) = fenced_blocks(text, "yaml")
    names = {"binding", *(span for row in table("Defaults") for span in row.spans(0))}

    rows = record_rows(block)

    assert rows[0] == "binding"
    assert sorted(set(rows) - names) == []
    assert block.splitlines()[0].startswith("# yaml-language-server: $schema=")
    assert block.splitlines()[1] == RECORD_START
    # The skill gives the format of a line, and the check reads it.
    assert '# - <row>: <choice>. Prompt: "<words of the prompt>"' in text
    assert RECORD_LINE.fullmatch('# - binding: nextjs, in the folder nextjs. Prompt: "an app"')
    assert not RECORD_LINE.fullmatch("# - binding: nextjs")
