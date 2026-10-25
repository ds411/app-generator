"""Tests of the data files of the seed: YAML, JSON, and CSV files (ADR 0021)."""

import json
from pathlib import Path

import pytest

from appgen.dsl import AppDefinition, DefinitionError, load_definition
from appgen.dsl.seed import SeedRecord
from appgen.dsl.validator import validate_definition
from appgen.gen import find_binding, generate, read_manifest, write_result
from appgen.trace import check_traces

BASE = """\
version: 0
app: { name: offices, title: Offices }
entities:
  Office:
    fields:
      name: { type: string, required: true, unique: true }
  Room:
    fields:
      code: { type: string, required: true }
      capacity: { type: integer, min: 1, max: 50 }
      price: { type: decimal }
      bookable: { type: boolean, default: true }
      opened_on: { type: date }
      checked_at: { type: datetime }
      settings: { type: json }
    relations:
      office: { kind: many_to_one, target: Office, required: true }
      features: { kind: many_to_many, target: Feature }
  Feature:
    fields:
      label: { type: string, required: true }
seed:
  Office:
    records:
      hq: { name: Head office }
  Feature:
    records:
      screen: { label: Screen }
      board: { label: Whiteboard }
"""

ROOMS_CSV = """\
key,code,capacity,price,bookable,opened_on,checked_at,settings,office,features
a101,A101,8,120.50,true,2020-03-01,2026-01-05T09:00:00Z,"{""floor"": 1}",hq,screen;board
a102,A102,,,FALSE,,,,hq,
"""


def write(folder: Path, files: dict[str, str], seed: str, base: str = BASE) -> Path:
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    path = folder / "app.yaml"
    path.write_text(base + seed, encoding="utf-8")
    return path


def load(folder: Path, files: dict[str, str], seed: str, base: str = BASE) -> AppDefinition:
    return load_definition(write(folder, files, seed, base))


def load_error(folder: Path, files: dict[str, str], seed: str) -> list[tuple[str, str, int]]:
    """Return the code, the file name, and the line of each diagnostic of the loader."""
    with pytest.raises(DefinitionError) as error:
        load(folder, files, seed)
    return [(d.code, Path(d.location.file).name, d.location.line) for d in error.value.diagnostics]


ROOM_FILE = "  Room:\n    file: data/rooms.csv\n"


def test_the_rows_of_a_csv_file_are_records_with_typed_values(tmp_path: Path) -> None:
    definition = load(tmp_path, {"data/rooms.csv": ROOMS_CSV}, ROOM_FILE)

    assert validate_definition(definition) == []
    first = definition.find("seed.Room.records.a101")
    second = definition.find("seed.Room.records.a102")
    assert isinstance(first, SeedRecord)
    assert isinstance(second, SeedRecord)
    assert first.values == {
        "code": "A101",
        "capacity": 8,
        "price": 120.5,
        "bookable": True,
        "opened_on": "2020-03-01",
        "checked_at": "2026-01-05T09:00:00Z",
        "settings": {"floor": 1},
        "office": "hq",
        "features": ["screen", "board"],
    }
    # An empty cell is no value.
    assert second.values == {"code": "A102", "bookable": False, "office": "hq"}
    assert first.location is not None
    assert (Path(first.location.file).name, first.location.line) == ("rooms.csv", 2)
    assert definition.seed["Room"].file == "data/rooms.csv"


def test_a_yaml_file_and_a_json_file_hold_records_as_records_does(tmp_path: Path) -> None:
    files = {
        "rooms.yaml": "a101:\n  code: A101\n  office: hq\n  opened_on: 2020-03-01\n",
        "features.json": json.dumps({"lamp": {"label": "Lamp"}}, indent=2),
    }
    base = BASE.replace(
        "  Feature:\n    records:", "  Feature:\n    file: features.json\n    records:"
    )

    definition = load(tmp_path, files, "  Room:\n    file: rooms.yaml\n", base)

    assert validate_definition(definition) == []
    record = definition.find("seed.Room.records.a101")
    assert isinstance(record, SeedRecord)
    assert record.location is not None
    assert (Path(record.location.file).name, record.location.line) == ("rooms.yaml", 1)
    assert record.location_of("office") is not None
    assert definition.find("seed.Feature.records.lamp") is not None
    assert definition.find("seed.Feature.records.screen") is not None


def test_a_diagnostic_of_a_record_of_a_file_gives_the_file_and_the_line(tmp_path: Path) -> None:
    csv = "key,code,capacity,office\na101,A101,8,hq\na102,A102,99,main\n"

    diagnostics = validate_definition(
        load(tmp_path, {"rooms.csv": csv}, "  Room:\n    file: rooms.csv\n")
    )

    assert [
        (d.code, Path(d.location.file).name, d.location.line, d.element_id) for d in diagnostics
    ] == [
        ("invalid-value", "rooms.csv", 3, "seed.Room.records.a102"),
        ("unknown-reference", "rooms.csv", 3, "seed.Room.records.a102"),
    ]


def test_a_key_in_records_and_in_the_file_is_an_error(tmp_path: Path) -> None:
    seed = "  Room:\n    file: rooms.csv\n    records:\n      a101: { code: A101, office: hq }\n"

    assert load_error(tmp_path, {"rooms.csv": "key,code,office\na101,A101,hq\n"}, seed) == [
        ("duplicate-key", "rooms.csv", 2)
    ]


@pytest.mark.parametrize(
    ("csv", "expected"),
    [
        ("key,code,capacity,office\na101,A101,eight,hq\n", ("invalid-value", 2)),
        ("key,code,price,office\na101,A101,1.2.3,hq\n", ("invalid-value", 2)),
        ("key,code,bookable,office\na101,A101,yes,hq\n", ("invalid-value", 2)),
        ("key,code,settings,office\na101,A101,{floor},hq\n", ("invalid-value", 2)),
        ("key,code,colour\na101,A101,red\n", ("unknown-key", 1)),
        ("code,office\nA101,hq\n", ("invalid-data-file", 1)),
        ("key,code,office\na101,A101,hq,extra\n", ("invalid-data-file", 2)),
        ("key,code,office\n,A101,hq\n", ("missing-key", 2)),
        ("key,code,office\na101,A101,hq\n\na101,A102,hq\n", ("duplicate-key", 4)),
        ("key,code,code\na101,A101,A102\n", ("duplicate-key", 1)),
        ("", ("invalid-data-file", 1)),
    ],
)
def test_a_csv_file_that_is_not_valid_is_an_error(
    tmp_path: Path, csv: str, expected: tuple[str, int]
) -> None:
    code, line = expected

    assert load_error(tmp_path, {"rooms.csv": csv}, "  Room:\n    file: rooms.csv\n") == [
        (code, "rooms.csv", line)
    ]


def test_an_unknown_column_gets_a_hint(tmp_path: Path) -> None:
    with pytest.raises(DefinitionError) as error:
        load(tmp_path, {"rooms.csv": "key,cod\na101,A101\n"}, "  Room:\n    file: rooms.csv\n")

    (diagnostic,) = error.value.diagnostics
    assert diagnostic.hint == "Did you mean 'code'?"


def test_a_cell_with_a_line_break_keeps_the_line_of_its_row(tmp_path: Path) -> None:
    csv = 'key,code,office\na101,"A\n101",hq\na102,A102,main\n'

    diagnostics = validate_definition(
        load(tmp_path, {"rooms.csv": csv}, "  Room:\n    file: rooms.csv\n")
    )

    assert [(d.element_id, d.location.line) for d in diagnostics] == [("seed.Room.records.a102", 4)]


@pytest.mark.parametrize(
    ("file", "files", "message"),
    [
        ("https://example.com/rooms.csv", {}, "not a URL"),
        ("missing.csv", {}, "does not exist"),
        ("rooms.txt", {"rooms.txt": "a101: {}\n"}, ".csv file"),
        ("rooms.yaml", {"rooms.yaml": "- a101\n"}, "must be a mapping"),
        ("rooms.json", {"rooms.json": '{"a101": '}, "not valid JSON"),
    ],
)
def test_a_data_file_must_be_a_local_file_with_records(
    tmp_path: Path, file: str, files: dict[str, str], message: str
) -> None:
    with pytest.raises(DefinitionError) as error:
        load(tmp_path, files, f"  Room:\n    file: {file}\n")

    (diagnostic,) = error.value.diagnostics
    assert diagnostic.code == "invalid-data-file"
    assert diagnostic.element_id == "seed.Room"
    assert message in diagnostic.message


def test_a_yaml_error_in_a_data_file_gives_its_line(tmp_path: Path) -> None:
    files = {"rooms.yaml": "a101:\n  code: A101\n  office: [hq\n"}

    assert load_error(tmp_path, files, "  Room:\n    file: rooms.yaml\n") == [
        ("yaml-syntax", "rooms.yaml", 4)
    ]


def test_the_manifest_records_the_hash_of_each_data_file(tmp_path: Path) -> None:
    folder = tmp_path / "def"
    folder.mkdir()
    path = write(folder, {"data/rooms.csv": ROOMS_CSV}, ROOM_FILE)
    binding = find_binding("minimal")
    out = tmp_path / "out"

    def documents() -> dict[str, str]:
        write_result(generate(load_definition(path), binding), out, binding.name)
        manifest = read_manifest(out)
        assert manifest is not None
        return manifest.documents

    first = documents()
    again = documents()
    (folder / "data" / "rooms.csv").write_text(ROOMS_CSV.replace("A102", "A103"))
    changed = documents()

    assert list(first) == ["data/rooms.csv"]
    assert first["data/rooms.csv"].startswith("sha256:")
    assert again == first
    assert changed["data/rooms.csv"] != first["data/rooms.csv"]


def test_a_trace_to_a_record_of_a_file_is_valid(tmp_path: Path) -> None:
    folder = tmp_path / "def"
    folder.mkdir()
    definition = load(folder, {"data/rooms.csv": ROOMS_CSV}, ROOM_FILE)
    app = tmp_path / "app"
    app.mkdir()
    (app / "seed.ts").write_text(
        "// @trace:manual seed.Room.records.a101\n// @trace:manual seed.Room.records.a109\n"
    )

    report = check_traces(definition, app)

    assert [problem.element_id for problem in report.invalid] == ["seed.Room.records.a109"]
