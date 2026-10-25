"""Tests of the seed records in the bindings: the mock data, React, and Next.js (ADR 0021)."""

import hashlib
import json
from pathlib import Path

import pytest

from appgen.bindings.fastapi.pysource import literal
from appgen.bindings.nextjs.db import build_tables, seed_tables
from appgen.bindings.shared.mock_data import mock_data, seed_records
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.dsl.seed import record_id
from appgen.gen import find_binding, generate, write_result
from appgen.trace import check_traces

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "seed-data.yaml"

BASE = """\
version: 0
app: { name: offices, title: Offices }
entities:
  Office:
    fields:
      name: { type: string, required: true, unique: true }
      city: { type: string, default: Berlin }
    relations:
      manager: { kind: one_to_one, target: Person, inverse: office }
      features: { kind: many_to_many, target: Feature, inverse: offices }
  Person:
    fields:
      email: { type: email, required: true, unique: true }
    relations:
      office: { kind: one_to_one, target: Office, inverse: manager }
  Feature:
    fields:
      label: { type: string, required: true }
    relations:
      offices: { kind: many_to_many, target: Office, inverse: features }
  Room:
    x-mock-count: 5
    fields:
      code: { type: string, required: true }
    relations:
      office: { kind: many_to_one, target: Office, required: true }
"""

SEED = """\
seed:
  Office:
    mock: 2
    records:
      hq: { name: Head office, features: [screen] }
      lisbon: { name: Lisbon office, city: Lisbon }
  Person:
    mock: 3
    records:
      ada: { email: ada@example.com, office: hq }
  Feature:
    records:
      screen: { label: Screen }
      board: { label: Whiteboard, offices: [lisbon, hq] }
"""


@pytest.fixture(scope="module")
def definition() -> AppDefinition:
    return load_definition_text(BASE + SEED)


def test_the_seed_records_come_first_with_their_fixed_ids(definition: AppDefinition) -> None:
    data = mock_data(definition)

    offices = data["Office"]
    assert [record["id"] for record in offices[:2]] == [
        record_id("offices", "Office", "hq"),
        record_id("offices", "Office", "lisbon"),
    ]
    assert len(offices) == 4  # Two seed records and `mock: 2`.
    assert len(data["Feature"]) == 2  # `mock` is 0 by default.
    assert len(data["Room"]) == 5  # An entity without a seed keeps `x-mock-count`.
    assert offices[0]["name"] == "Head office"


def test_a_field_without_a_value_gets_its_default(definition: AppDefinition) -> None:
    hq, lisbon = mock_data(definition)["Office"][:2]

    assert (hq["city"], lisbon["city"]) == ("Berlin", "Lisbon")


def test_both_sides_of_a_relation_get_the_links_of_the_seed(definition: AppDefinition) -> None:
    seeds = seed_records(definition)
    hq, lisbon = seeds["Office"]
    (ada,) = seeds["Person"]
    screen, board = seeds["Feature"]

    assert hq["manager"] == ada["id"]
    assert ada["office"] == hq["id"]
    assert hq["features"] == [screen["id"], board["id"]]
    assert lisbon["features"] == [board["id"]]
    assert screen["offices"] == [hq["id"]]
    assert board["offices"] == [lisbon["id"], hq["id"]]


def test_the_generated_records_refer_to_the_seed_and_keep_its_values_free(
    definition: AppDefinition,
) -> None:
    data = mock_data(definition)
    office_ids = {record["id"] for record in data["Office"]}

    assert {room["office"] for room in data["Room"]} <= office_ids
    generated_people = data["Person"][1:]
    # The seed gives Ada to the head office, so no generated person gets it.
    assert all(person["office"] != data["Office"][0]["id"] for person in generated_people)
    emails = [person["email"] for person in data["Person"]]
    assert len(set(emails)) == len(emails)
    names = [office["name"] for office in data["Office"]]
    assert len(set(names)) == len(names)


def test_an_empty_seed_gives_no_target_to_an_optional_relation() -> None:
    definition = load_definition_text(
        BASE.replace("required: true }\n", "}\n", 1).replace(
            "office: { kind: many_to_one, target: Office, required: true }",
            "office: { kind: many_to_one, target: Office }",
        )
        + "seed:\n  Office:\n    records: {}\n"
    )

    data = mock_data(definition)

    assert data["Office"] == []
    assert {room["office"] for room in data["Room"]} == {None}


@pytest.mark.parametrize(
    ("example", "digest"),
    [
        ("project-tracker", "8d6e2713b769c3fafd7a2ce30e5bc3cdf59951758657d91e581247b3c37b7c80"),
        ("room-booking", "abcb48e23d20a6069a9f52da0f235bfb0dc9ec0c52da839c5be0836343aca506"),
    ],
)
def test_a_definition_without_a_seed_keeps_its_mock_data(example: str, digest: str) -> None:
    # The approved screenshots show these records.
    data = mock_data(load_definition(ROOT / "examples" / example / "app.yaml"))

    assert hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() == digest


def test_the_nextjs_seed_splits_the_seed_records_from_the_generated_records(
    definition: AppDefinition,
) -> None:
    seeds = {seed.table.entity: seed for seed in seed_tables(definition, build_tables(definition))}

    office = seeds["Office"]
    assert office.seed_id == "seed.Office"
    assert [record.element_id for record in office.records] == [
        "seed.Office.records.hq",
        "seed.Office.records.lisbon",
    ]
    assert len(office.rows) == 2
    assert office.records_const == "officeRecords"
    assert office.record_links_const == "officeRecordLinks"
    assert seeds["Room"].records == []
    assert seeds["Room"].seed_id is None


@pytest.mark.parametrize("binding_name", ["react", "nextjs", "fastapi"])
def test_the_apps_cover_each_seed_record(binding_name: str, tmp_path: Path) -> None:
    definition = load_definition(FIXTURE)
    binding = find_binding(binding_name)

    write_result(generate(definition, binding), tmp_path, binding.name)
    report = check_traces(definition, tmp_path)

    assert report.exit_code == 0
    seed_kinds = {"entity_seed", "seed_record"}
    assert [e.element_id for e in report.coverage.uncovered if e.kind in seed_kinds] == []
    covered = {kind.kind: kind.covered for kind in report.coverage.by_kind}
    assert covered["seed_record"] == 9
    assert covered["entity_seed"] == 4


def test_the_react_mock_data_holds_the_records_of_the_csv_file(tmp_path: Path) -> None:
    binding = find_binding("react")
    write_result(generate(load_definition(FIXTURE), binding), tmp_path, binding.name)

    text = (tmp_path / "src/entities/room/api/room-mock-data.ts").read_text()

    assert "// @trace seed.Room\n" in text
    assert "  // @trace seed.Room.records.a101\n" in text
    assert '"code": "A101"' in text
    assert '"id": "' + record_id("seed-data", "Room", "a101") + '"' in text


def test_the_nextjs_seed_inserts_the_seed_records_by_id(tmp_path: Path) -> None:
    binding = find_binding("nextjs")
    write_result(generate(load_definition(FIXTURE), binding), tmp_path, binding.name)

    seed = (tmp_path / "src/shared/db/seed.ts").read_text()
    data = (tmp_path / "src/shared/db/seed-data.ts").read_text()

    assert ".onConflictDoNothing({ target: roomTable.id })" in seed
    assert "  // @trace seed.Room.records.l201\n" in data
    assert "export const roomRecords:" in data
    assert "personAdded.has(String(row.id))" in seed


def test_the_fastapi_seed_has_typed_rows_in_the_order_of_the_required_keys(
    tmp_path: Path,
) -> None:
    binding = find_binding("fastapi")
    write_result(generate(load_definition(FIXTURE), binding), tmp_path, binding.name)

    data = (tmp_path / "app/core/seed_data.py").read_text()
    a101 = record_id("seed-data", "Room", "a101")

    assert "    # @trace seed.Room.records.a101\n" in data
    assert f'        "id": UUID("{a101}"),\n' in data
    assert '        "price": Decimal("120.5"),\n' in data
    assert '        "checked_at": dt.datetime.fromisoformat("2026-01-05T09:00:00Z"),\n' in data
    assert '        "settings": {"floor": 1},\n' in data
    # The optional key of the one_to_one relation is a link: the seed sets it after the inserts.
    assert "OFFICES_RECORD_LINKS: list[Row] = [" in data
    tables = data[data.index("TABLES: list[SeedTable]") :]
    assert tables.index('"offices"') < tables.index('"rooms"') < tables.index('"bookings"')
    assert '        "rooms_features",\n        "rooms",\n        "room_id",\n' in data
    assert "        records=ROOMS_FEATURES_RECORDS,\n" in data


def test_the_fastapi_seed_test_changes_and_deletes_seed_records(tmp_path: Path) -> None:
    binding = find_binding("fastapi")
    write_result(generate(load_definition(FIXTURE), binding), tmp_path, binding.name)

    test = (tmp_path / "tests/test_seed.py").read_text()

    assert '    "credentials": 2,\n' in test
    assert "async def test_a_second_seed_adds_a_deleted_seed_record_and_keeps_a_change(" in test
    assert "    assert added == 1\n" in test


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"floor": 1, "tags": [True, None]}, '"settings": {"floor": 1, "tags": [True, None]},'),
        ("It's", '"settings": "It\'s",'),
        (
            {"text": "x" * 50, "list": ["y" * 30, 2.5]},
            '"settings": {\n'
            + f'            "text": "{"x" * 50}",\n'
            + f'            "list": ["{"y" * 30}", 2.5],\n'
            + "        },",
        ),
    ],
)
def test_a_json_value_is_a_python_literal_in_the_format_of_ruff(
    value: object, expected: str
) -> None:
    assert literal(value, '"settings": ', 8, ",") == expected
