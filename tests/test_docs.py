"""Tests of the user docs: the examples are valid, and the links work.

Each YAML block of the DSL reference is valid. A complete definition
(with `version`) is valid alone. A fragment of one section goes into a
base definition, and `appgen validate` gives no diagnostic for the
result. Comments on the first lines of a fragment tell where it goes:

- `# in: <path>`: the place of the fragment, for example
  `entities.Task`. The default is the root of the definition.
- `# example: <name>`: the base definition `examples/<name>/app.yaml`.
  The default is `project-tracker`.
- `# not valid alone: <reason>`: the fragment needs more than a base
  definition. The test checks that the fragment is not valid.

The fragment and the base merge as mappings: a key of the fragment adds
to the mapping of the base, and replaces a value that is not a mapping.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from skill_support import code_blocks

from appgen.dsl import DefinitionError, Diagnostic, Location, validate_definition
from appgen.dsl.loader import _load  # pyright: ignore[reportPrivateUsage]
from appgen.dsl.source import DataPath, SourceMap, YamlDocument, read_yaml, read_yaml_file
from appgen.gen import available_bindings, find_binding
from appgen.gen.extensions import check_extensions

ROOT = Path(__file__).parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
DSL = "docs/dsl.md"
BASE = "project-tracker"
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
_MARKER = re.compile(r"# (in|example|not valid alone): (.+)")


@dataclass(frozen=True)
class Fragment:
    """A YAML block of a doc, and where it goes."""

    line: int
    """The line of the first line of the block in the doc."""
    text: str
    place: DataPath
    example: str
    skip: str | None
    """The reason why the fragment is not valid alone, or None."""


def fragments(text: str) -> list[Fragment]:
    """Return the YAML blocks of a doc with their markers."""
    found: list[Fragment] = []
    for block in code_blocks(text, "yaml"):
        markers: dict[str, str] = {}
        for line in block.content.splitlines():
            if not line.startswith("#"):
                break
            if match := _MARKER.fullmatch(line):
                markers[match.group(1)] = match.group(2).strip()
        place = markers.get("in", "")
        found.append(
            Fragment(
                line=block.line,
                text=block.content,
                place=tuple(place.split(".")) if place else (),
                example=markers.get("example", BASE),
                skip=markers.get("not valid alone"),
            )
        )
    return found


def _merge(base: object, fragment: object) -> object:
    if isinstance(base, dict) and isinstance(fragment, dict):
        merged = dict(cast(dict[str, object], base))
        for key, value in cast(dict[str, object], fragment).items():
            merged[key] = _merge(merged[key], value) if key in merged else value
        return merged
    return fragment


def _moved(location: Location, offset: int) -> Location:
    return Location(DSL, location.line + offset, location.column)


def place_fragment(fragment: Fragment) -> tuple[YamlDocument, Path]:
    """Return the definition with the fragment, and the folder of its files.

    The locations of the nodes of the fragment are in docs/dsl.md.
    """
    document = read_yaml(fragment.text, DSL)
    data = document.data
    if not fragment.place and "version" in cast(dict[str, object], data):
        base = YamlDocument(None, SourceMap(DSL, Location(DSL, fragment.line, 1)))
        folder = ROOT / "docs"
    else:
        path = ROOT / "examples" / fragment.example / "app.yaml"
        base = read_yaml_file(path)
        folder = path.parent
    for key in reversed(fragment.place):
        data = {key: data}
    source_map = SourceMap(
        base.source_map.file,
        base.source_map.root,
        dict(base.source_map.keys),
        dict(base.source_map.values),
        dict(base.source_map.booleans),
    )
    offset = fragment.line - 1
    for path, location in document.source_map.keys.items():
        source_map.keys[(*fragment.place, *path)] = _moved(location, offset)
    for path, location in document.source_map.values.items():
        source_map.values[(*fragment.place, *path)] = _moved(location, offset)
    for path, text in document.source_map.booleans.items():
        source_map.booleans[(*fragment.place, *path)] = text
    merged = data if base.data is None else _merge(base.data, data)
    return YamlDocument(merged, source_map), folder


def validate(document: YamlDocument, folder: Path) -> list[Diagnostic]:
    """Return the diagnostics of `appgen validate` for a definition."""
    try:
        definition = _load(document, folder)
    except DefinitionError as error:
        return error.diagnostics
    bindings = [find_binding(name) for name in available_bindings()]
    return [*validate_definition(definition), *check_extensions(definition, bindings)]


def fragment_errors(text: str) -> list[str]:
    """Return a message for each fragment of a doc that is not valid, or wrongly marked."""
    errors: list[str] = []
    for fragment in fragments(text):
        if read_yaml(fragment.text, DSL).data is None:
            continue
        diagnostics = validate(*place_fragment(fragment))
        if fragment.skip is not None:
            if not diagnostics:
                errors.append(
                    f"{DSL}:{fragment.line}: the fragment is valid, so remove the marker "
                    f"'# not valid alone: {fragment.skip}'"
                )
            continue
        for diagnostic in diagnostics:
            where = "" if diagnostic.location.file == DSL else f"{DSL}:{fragment.line}: in "
            errors.append(f"{where}{diagnostic}")
    return errors


def test_the_yaml_blocks_of_the_dsl_reference_are_valid() -> None:
    text = (ROOT / DSL).read_text(encoding="utf-8")

    assert len([f for f in fragments(text) if f.skip is None]) >= 20
    assert fragment_errors(text) == []


def test_the_fragment_check_gives_the_line_of_an_unknown_key() -> None:
    text = (
        "Text.\n\n"
        "```yaml\n"
        "# in: entities.Task\n"
        "fields:\n"
        "  title: { type: string, max_lenght: 80 }\n"
        "```\n"
    )

    (error,) = fragment_errors(text)

    assert error.startswith(f"{DSL}:6:")
    assert "error[unknown-key]" in error
    assert "max_lenght" in error


def test_the_fragment_check_merges_into_the_base_and_reads_the_markers() -> None:
    text = (
        "```yaml\n"
        "# in: entities.Task\n"
        "fields:\n"
        "  estimate: { type: integer, min: 0 }\n"
        "```\n\n"
        "```yaml\n"
        "# example: room-booking\n"
        "workflows:\n"
        "  booking_status:\n"
        "    entity: Booking\n"
        "    field: status\n"
        "    transitions:\n"
        "      confirm: { from: [requested], to: confirmed }\n"
        "```\n\n"
        "```yaml\n"
        "# not valid alone: the views refer to a form of another example.\n"
        "pages:\n"
        "  rooms: { path: /rooms, title: Rooms, content: { form: book_room } }\n"
        "```\n"
    )

    assert fragment_errors(text) == []


def test_the_fragment_check_fails_for_a_marker_on_a_valid_fragment() -> None:
    text = (
        "```yaml\n"
        "# not valid alone: no reason.\n"
        "operations:\n"
        "  list_tasks: { kind: list, entity: Task }\n"
        "```\n"
    )

    assert fragment_errors(text) == [
        f"{DSL}:2: the fragment is valid, so remove the marker '# not valid alone: no reason.'"
    ]


def test_the_fragment_check_gives_a_diagnostic_of_the_base_at_the_fragment() -> None:
    # The base refers to the field `status` of Task, and the fragment
    # makes it a field of another type.
    text = "```yaml\n# in: entities.Task.fields\nstatus: { type: integer }\n```\n"

    errors = fragment_errors(text)

    assert errors
    assert all(e.startswith(f"{DSL}:2: in ") or e.startswith(f"{DSL}:3:") for e in errors)


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_the_local_links_of_the_docs_exist(doc: Path) -> None:
    for target in _LINK.findall(doc.read_text()):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        assert (doc.parent / target).exists(), f"{doc.name}: {target}"
