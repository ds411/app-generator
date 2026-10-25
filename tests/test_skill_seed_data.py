"""The skill tells an agent how to add seed records to a definition (ADR 0021).

The test does the steps of `references/seed-data.md` with its example:
the definition, a CSV file, and a YAML file. The definition validates,
the React app has the records in its mock data, and the Next.js and
FastAPI apps have the seed commands of the reference.
"""

import re
from pathlib import Path

import pytest
from skill_support import SKILL, data_files, fenced_blocks

from appgen.dsl import check_file
from appgen.dsl.seed import record_id
from appgen.gen import find_binding, generate, write_result
from appgen.trace import check_traces

REFERENCE = SKILL / "references" / "seed-data.md"


@pytest.fixture(scope="module")
def definition_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The example of the reference, with its data files, in a new folder."""
    text = REFERENCE.read_text(encoding="utf-8")
    folder = tmp_path_factory.mktemp("seed-data")
    for file, content in data_files(text).items():
        (folder / file).parent.mkdir(parents=True, exist_ok=True)
        (folder / file).write_text(content, encoding="utf-8")
    (block,) = [b for b in fenced_blocks(text, "yaml") if re.search(r"^version: 0$", b, re.M)]
    path = folder / "app.yaml"
    path.write_text(block, encoding="utf-8")
    return path


def test_the_example_has_a_csv_file_and_a_yaml_file(definition_path: Path) -> None:
    files = data_files(REFERENCE.read_text(encoding="utf-8"))

    assert sorted(files) == ["data/features.yaml", "data/rooms.csv"]
    for file in files:
        assert f"file: {file}" in definition_path.read_text(encoding="utf-8")


def test_the_react_app_has_the_records_of_the_csv_file(
    definition_path: Path, tmp_path: Path
) -> None:
    definition, diagnostics = check_file(definition_path)
    assert diagnostics == []
    assert definition is not None
    binding = find_binding("react")

    write_result(generate(definition, binding), tmp_path, binding.name)
    report = check_traces(definition, tmp_path)

    assert report.exit_code == 0
    assert not [e for e in report.coverage.uncovered if e.element_id.startswith("seed.")]
    rooms = (tmp_path / "src/entities/room/api/room-mock-data.ts").read_text(encoding="utf-8")
    csv = data_files(REFERENCE.read_text(encoding="utf-8"))["data/rooms.csv"]
    for row in csv.splitlines()[1:]:
        key, code = row.split(",")[:2]
        assert f"// @trace seed.Room.records.{key}\n" in rooms
        assert f'"id": "{record_id("offices", "Room", key)}"' in rooms
        assert f'"code": "{code}"' in rooms
    # Two seed records and `mock: 2`: the generated records follow the seed records.
    assert rooms.count('"code": ') == len(csv.splitlines()) - 1 + 2


@pytest.mark.parametrize(
    ("binding_name", "file", "command"),
    [
        ("nextjs", "package.json", '"db:seed":'),
        ("fastapi", "app/cli.py", 'case ["seed"]:'),
    ],
)
def test_the_apps_have_the_seed_commands_of_the_reference(
    definition_path: Path, tmp_path: Path, binding_name: str, file: str, command: str
) -> None:
    definition, _ = check_file(definition_path)
    assert definition is not None
    binding = find_binding(binding_name)

    write_result(generate(definition, binding), tmp_path, binding.name)

    assert command in (tmp_path / file).read_text(encoding="utf-8")
    reference = REFERENCE.read_text(encoding="utf-8")
    assert "`pnpm db:seed`" in reference
    assert "`uv run python -m app.cli seed`" in reference
