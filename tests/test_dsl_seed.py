"""Tests of the `seed` section: the model, the record IDs, and the validator (ADR 0021)."""

import datetime

import pytest

from appgen.dsl import AppDefinition, DefinitionError, load_definition_text
from appgen.dsl.seed import EntitySeed, SeedRecord, normal_value, record_id
from appgen.dsl.validator import validate_definition
from appgen.gen import find_binding, generate
from appgen.gen.elements import iter_elements

BASE = """\
version: 0
app: { name: offices, title: Offices }
entities:
  Office:
    display_field: name
    fields:
      name: { type: string, required: true, unique: true, max_length: 20 }
      opened_on: { type: date }
      website: { type: url }
    relations:
      rooms: { kind: one_to_many, target: Room, inverse: office }
      manager: { kind: one_to_one, target: Person, inverse: office }
  Room:
    fields:
      code: { type: string, required: true, pattern: "^[A-Z][0-9]{3}$" }
      capacity: { type: integer, min: 1, max: 50, default: 4 }
      price: { type: decimal, precision: 6, scale: 2 }
      kind: { type: enum, values: [meeting, focus], default: meeting }
      price_per_seat: { type: decimal, computed: price / capacity }
      settings: { type: json }
    relations:
      office: { kind: many_to_one, target: Office, required: true }
      features: { kind: many_to_many, target: Feature }
    rules:
      one_code_per_office: { kind: unique, fields: [office, code] }
  Feature:
    fields:
      label: { type: string, required: true, min_length: 2 }
  Person:
    fields:
      email: { type: email, required: true, unique: true }
      external_id: { type: uuid }
    relations:
      office: { kind: one_to_one, target: Office, inverse: manager }
  Booking:
    fields:
      starts_at: { type: datetime, required: true }
      ends_at: { type: datetime, required: true }
    relations:
      room: { kind: many_to_one, target: Room, required: true }
    rules:
      ends_after_start:
        kind: compare
        field: ends_at
        op: gt
        other: starts_at
        message: The end must be after the start.
      no_double_booking:
        kind: no_overlap
        start: starts_at
        end: ends_at
        scope: [room]
        message: The room is booked at this time.
"""

SEED = """\
seed:
  Office:
    records:
      hq: { name: Head office, opened_on: 2020-03-01, manager: ada }
      branch: { name: Branch, website: "https://branch.example.com" }
  Room:
    mock: 3
    records:
      r101: { code: A101, office: hq, capacity: 8, price: 120.5, features: [screen, board] }
      r102: { code: A102, office: hq, kind: focus }
  Feature:
    records:
      screen: { label: Screen }
      board: { label: Whiteboard }
  Person:
    records:
      ada: { email: ada@example.com, external_id: 6F9619FF-8B86-D011-B42D-00C04FC964FF }
  Booking:
    records:
      first:
        room: r101
        starts_at: 2026-01-05T09:00:00Z
        ends_at: "2026-01-05T11:00:00+01:00"
"""


def load(seed: str = SEED) -> AppDefinition:
    return load_definition_text(BASE + seed, "app.yaml")


def problems(seed: str) -> list[tuple[str, str | None, int]]:
    """Return the code, the element ID, and the line of each diagnostic of a seed."""
    return [(d.code, d.element_id, d.location.line) for d in validate_definition(load(seed))]


def line_of(seed: str, text: str) -> int:
    """Return the line of a text in the definition of a seed."""
    lines = (BASE + seed).splitlines()
    return next(number for number, line in enumerate(lines, 1) if text in line)


def test_a_valid_seed_has_no_diagnostics() -> None:
    assert validate_definition(load()) == []


def test_each_seed_and_each_record_is_an_element() -> None:
    definition = load()

    kinds = {e.id: e.kind for e in iter_elements(definition) if e.id.startswith("seed.")}

    assert kinds["seed.Office"] == "entity_seed"
    assert kinds["seed.Office.records.hq"] == "seed_record"
    assert kinds["seed.Booking.records.first"] == "seed_record"
    seed = definition.seed["Room"]
    assert isinstance(seed, EntitySeed)
    assert seed.mock == 3
    assert definition.seed["Office"].mock == 0
    record = definition.find("seed.Room.records.r101")
    assert isinstance(record, SeedRecord)
    assert record.key == "r101"
    assert record.values["features"] == ["screen", "board"]
    assert record.location is not None
    assert record.location.line == line_of(SEED, "r101:")


def test_the_id_of_a_record_comes_from_the_app_the_entity_and_the_key() -> None:
    first = record_id("offices", "Room", "r101")

    assert first == record_id("offices", "Room", "r101")
    # A UUID of version 5. The value must not change, because the apps store it.
    assert first == "e984ac8c-b98c-5016-9f05-971ad0ab5d25"
    assert (
        len({first, record_id("shop", "Room", "r101"), record_id("offices", "Desk", "r101")}) == 3
    )
    assert record_id("offices", "Room", "r102") != first


def test_a_change_of_another_record_does_not_change_an_id() -> None:
    before = load()
    after = load(SEED.replace("r102: { code: A102", "r103: { code: A103"))

    assert before.find("seed.Room.records.r101") is not None
    assert after.find("seed.Room.records.r101") is not None
    assert record_id(before.app.name, "Room", "r101") == record_id(after.app.name, "Room", "r101")


@pytest.mark.parametrize(
    ("field_type", "value", "expected"),
    [
        ("date", datetime.date(2026, 1, 5), "2026-01-05"),
        ("date", "2026-01-05", "2026-01-05"),
        ("datetime", "2026-01-05T11:00:00+01:00", "2026-01-05T10:00:00Z"),
        ("datetime", "2026-01-05T09:30:00", "2026-01-05T09:30:00Z"),
        ("datetime", "2026-01-05T09:30:00.250Z", "2026-01-05T09:30:00.250Z"),
        (
            "datetime",
            datetime.datetime(2026, 1, 5, 9, 30, tzinfo=datetime.UTC),
            "2026-01-05T09:30:00Z",
        ),
        ("uuid", "6F9619FF-8B86-D011-B42D-00C04FC964FF", "6f9619ff-8b86-d011-b42d-00c04fc964ff"),
        ("decimal", 3, 3),
        ("json", {"a": [1, None]}, {"a": [1, None]}),
        ("string", None, None),
    ],
)
def test_the_normal_form_of_a_value(field_type: str, value: object, expected: object) -> None:
    definition = load_definition_text(
        f"version: 0\napp: {{ name: a, title: A }}\nentities:\n"
        f"  Item:\n    fields:\n      value: {{ type: {field_type} }}\n"
    )
    field = definition.entities["Item"].fields["value"]

    assert normal_value(field, value) == expected


@pytest.mark.parametrize(
    ("seed", "text", "code", "element"),
    [
        (
            "  Feature:\n    records:\n      a: { label: Screen, colour: red }\n",
            "colour",
            "unknown-key",
            "seed.Feature.records.a",
        ),
        (
            "  Feature:\n    records:\n      a: { label: Screen, id: x }\n",
            "id: x",
            "unknown-key",
            "seed.Feature.records.a",
        ),
        (
            "  Feature:\n    records:\n      a: { label: 12 }\n",
            "label: 12",
            "invalid-value",
            "seed.Feature.records.a",
        ),
        (
            "  Feature:\n    records:\n      a: { label: x }\n",
            "label: x",
            "invalid-value",
            "seed.Feature.records.a",
        ),
        (
            "  Feature:\n    records:\n      a: {}\n",
            "a: {}",
            "missing-key",
            "seed.Feature.records.a",
        ),
    ],
)
def test_a_wrong_value_gives_a_diagnostic_at_its_line(
    seed: str, text: str, code: str, element: str
) -> None:
    seed = "seed:\n" + seed

    assert problems(seed) == [(code, element, line_of(seed, text))]


ROOM = "seed:\n  Office:\n    records:\n      hq: { name: HQ }\n  Room:\n    records:\n"


@pytest.mark.parametrize(
    ("record", "code", "message"),
    [
        ("{ code: a101, office: hq }", "invalid-value", "must match the pattern"),
        ("{ code: A101, office: hq, capacity: 0 }", "invalid-value", "must be 1 or more"),
        ("{ code: A101, office: hq, capacity: 51 }", "invalid-value", "must be 50 or less"),
        ("{ code: A101, office: hq, capacity: 2.5 }", "invalid-value", "expected an integer"),
        ("{ code: A101, office: hq, capacity: '4' }", "invalid-value", "expected an integer"),
        ("{ code: A101, office: hq, price: 10000 }", "invalid-value", "4 or fewer digits"),
        ("{ code: A101, office: hq, kind: large }", "invalid-value", "expected one of"),
        ("{ code: A101, office: hq, price_per_seat: 3 }", "unsuitable-field", "is computed"),
        ("{ code: A101 }", "missing-key", "required relation 'office'"),
        ("{ code: A101, office: hq, rooms: [] }", "unknown-key", "has no field or relation"),
        ("{ code: A101, office: main }", "unknown-reference", "has no seed record 'main'"),
        ("{ code: A101, office: [hq] }", "invalid-value", "must be the key"),
        ("{ code: A101, office: hq, features: screen }", "invalid-value", "must be a list"),
        ("{ code: A101, office: hq, features: [screen] }", "unknown-reference", "'Feature'"),
        ("{ code: A101, office: hq, settings: 2026-01-05 }", "invalid-value", "JSON value"),
    ],
)
def test_a_value_must_suit_its_field_or_relation(record: str, code: str, message: str) -> None:
    diagnostics = validate_definition(load(ROOM + f"      r1: {record}\n"))

    assert [(d.code, d.element_id) for d in diagnostics] == [(code, "seed.Room.records.r1")]
    assert message in diagnostics[0].message


def test_a_value_that_yaml_reads_as_a_number_gets_a_hint() -> None:
    (diagnostic,) = validate_definition(
        load("seed:\n  Feature:\n    records:\n      a: { label: 12 }\n")
    )

    assert diagnostic.hint == 'Put the value in quotes: "12".'


def test_an_email_and_a_url_must_have_their_form() -> None:
    seed = (
        "seed:\n  Office:\n    records:\n      hq: { name: HQ, website: example.com }\n"
        "  Person:\n    records:\n      ada: { email: ada }\n"
    )

    assert [d.code for d in validate_definition(load(seed))] == ["invalid-value", "invalid-value"]


def test_a_one_to_many_relation_is_on_the_other_side() -> None:
    seed = "seed:\n  Office:\n    records:\n      hq: { name: HQ, rooms: [r1] }\n"

    (diagnostic,) = validate_definition(load(seed))

    assert diagnostic.code == "unsuitable-field"
    assert diagnostic.hint == "Give the key of this record in 'office' of the records of 'Room'."


@pytest.mark.parametrize(
    ("records", "code", "element"),
    [
        (
            "      hq: { name: HQ }\n      hq2: { name: HQ }\n",
            "duplicate-value",
            "seed.Office.records.hq2",
        ),
        (
            "      hq: { name: HQ, manager: ada }\n      hq2: { name: HQ 2, manager: ada }\n",
            "duplicate-value",
            "seed.Person.records.ada",
        ),
    ],
)
def test_a_unique_value_occurs_one_time(records: str, code: str, element: str) -> None:
    seed = (
        "seed:\n  Office:\n    records:\n" + records + "  Person:\n    records:\n"
        "      ada: { email: ada@example.com }\n"
    )

    assert [(d.code, d.element_id) for d in validate_definition(load(seed))] == [(code, element)]


def test_the_records_keep_the_unique_rule_of_the_entity() -> None:
    seed = ROOM + "      r1: { code: A101, office: hq }\n      r2: { code: A101, office: hq }\n"

    (diagnostic,) = validate_definition(load(seed))

    assert (diagnostic.code, diagnostic.element_id) == ("duplicate-value", "seed.Room.records.r2")
    assert "rule 'one_code_per_office'" in diagnostic.message
    assert "'r1'" in diagnostic.message


def test_a_unique_value_counts_the_default() -> None:
    seed = (
        "seed:\n  Feature:\n    records:\n      a: { label: Screen }\n"
        "      b: { label: Screen }\n      c: { label: null }\n"
    )
    definition = load_definition_text(
        BASE.replace(
            "label: { type: string, required: true, min_length: 2 }",
            "label: { type: string, unique: true, default: Screen }",
        )
        + seed
    )

    assert [(d.code, d.element_id) for d in validate_definition(definition)] == [
        ("duplicate-value", "seed.Feature.records.b")
    ]


BOOKING = ROOM + "      r1: { code: A101, office: hq }\n  Booking:\n    records:\n"


def test_the_records_keep_the_compare_rule_of_the_entity() -> None:
    seed = (
        BOOKING + "      b1: { room: r1, starts_at: 2026-01-05T10:00:00Z,"
        " ends_at: '2026-01-05T10:30:00+01:00' }\n"
    )

    (diagnostic,) = validate_definition(load(seed))

    assert (diagnostic.code, diagnostic.element_id) == ("invalid-record", "seed.Booking.records.b1")
    assert diagnostic.message.endswith("The end must be after the start.")


def test_the_records_keep_the_no_overlap_rule_of_the_entity() -> None:
    seed = (
        BOOKING
        + "      b1: { room: r1, starts_at: 2026-01-05T10:00:00Z, ends_at: 2026-01-05T11:00:00Z }\n"
        "      b2: { room: r1, starts_at: 2026-01-05T11:00:00Z, ends_at: 2026-01-05T12:00:00Z }\n"
        "      b3: { room: r1, starts_at: 2026-01-05T10:30:00Z, ends_at: 2026-01-05T10:45:00Z }\n"
    )

    (diagnostic,) = validate_definition(load(seed))

    assert (diagnostic.code, diagnostic.element_id) == ("invalid-record", "seed.Booking.records.b3")
    assert diagnostic.hint == "The time range of the record 'b1' overlaps."


def test_a_record_has_one_partner_in_a_one_to_one_relation() -> None:
    seed = (
        "seed:\n  Office:\n    records:\n      hq: { name: HQ, manager: ada }\n"
        "  Person:\n    records:\n      ada: { email: ada@example.com }\n"
        "      bob: { email: bob@example.com, office: hq }\n"
    )

    (diagnostic,) = validate_definition(load(seed))

    assert (diagnostic.code, diagnostic.element_id) == ("duplicate-value", "seed.Office.records.hq")
    assert "'ada' and 'bob'" in diagnostic.message


def test_both_sides_of_a_one_to_one_relation_can_agree() -> None:
    seed = (
        "seed:\n  Office:\n    records:\n      hq: { name: HQ, manager: ada }\n"
        "  Person:\n    records:\n      ada: { email: ada@example.com, office: hq }\n"
    )

    assert validate_definition(load(seed)) == []


def test_an_integer_key_refers_to_a_record() -> None:
    seed = "seed:\n  Office:\n    records:\n      1: { name: HQ }\n  Room:\n    records:\n"
    seed += "      101: { code: A101, office: 1 }\n"

    assert validate_definition(load(seed)) == []


def test_the_seed_of_an_unknown_entity_is_an_error() -> None:
    (diagnostic,) = validate_definition(load("seed:\n  Ofice:\n    records: {}\n"))

    assert diagnostic.code == "unknown-reference"
    assert diagnostic.hint == "Did you mean 'Office'?"


def test_a_required_relation_needs_a_record_of_its_target() -> None:
    (diagnostic,) = validate_definition(load("seed:\n  Office:\n    records: {}\n"))

    assert (diagnostic.code, diagnostic.element_id) == ("missing-key", "seed.Office")
    assert "'Room'" in diagnostic.message


@pytest.mark.parametrize(
    ("seed", "code"),
    [
        ("seed:\n  Office:\n    mock: -1\n", "invalid-value"),
        ("seed:\n  Office:\n    records:\n      head-office: { name: HQ }\n", "invalid-name"),
        ("seed:\n  Office:\n    records:\n      hq: [HQ]\n", "invalid-value"),
        ("seed:\n  Office:\n    rows: {}\n", "unknown-key"),
    ],
)
def test_the_loader_checks_the_structure_of_the_seed(seed: str, code: str) -> None:
    with pytest.raises(DefinitionError) as error:
        load(seed)

    assert [d.code for d in error.value.diagnostics] == [code]


@pytest.mark.parametrize("binding_name", ["nextjs", "react", "fastapi"])
def test_the_bindings_make_no_gaps_for_the_seed(binding_name: str) -> None:
    result = generate(load(), find_binding(binding_name))

    assert [gap.element_id for gap in result.gaps if gap.element_id.startswith("seed")] == []
