import re
from pathlib import Path
from typing import cast

import pytest

from appgen.bindings.react.helpers import members, mock_records
from appgen.bindings.shared.mock_data import DEFAULT_COUNT, mock_data
from appgen.dsl import AppDefinition, load_definition, load_definition_text

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module", params=["project-tracker", "edge-cases"])
def definition(request: pytest.FixtureRequest) -> AppDefinition:
    return load_definition(EXAMPLES / request.param / "app.yaml")


def test_the_data_is_the_same_on_each_run(definition: AppDefinition) -> None:
    assert mock_data(definition) == mock_data(definition)


def test_each_relation_refers_to_a_record_that_exists(definition: AppDefinition) -> None:
    data = mock_data(definition)
    ids = {name: {record["id"] for record in records} for name, records in data.items()}
    for name, entity in definition.entities.items():
        for record in data[name]:
            for relation_name, relation in entity.relations.items():
                if relation.kind == "one_to_many":
                    assert relation_name not in record
                    continue
                value = record[relation_name]
                targets = cast(list[str | None], value if isinstance(value, list) else [value])
                if relation.required:
                    assert value is not None, f"{name}.{relation_name}"
                assert all(t is None or t in ids[relation.target] for t in targets)


def test_the_values_suit_the_fields(definition: AppDefinition) -> None:
    data = mock_data(definition)
    for name, entity in definition.entities.items():
        assert len(data[name]) == DEFAULT_COUNT
        for field_name, field in entity.fields.items():
            values = [record[field_name] for record in data[name]]
            present = [v for v in values if v is not None]
            if field.required or field.default is not None:
                assert len(present) == len(values), f"{name}.{field_name}"
            if field.unique:
                assert len(set(present)) == len(present), f"{name}.{field_name}"
            for value in present:
                if field.type == "enum":
                    assert value in (field.values or [])
                if field.pattern is not None:
                    assert re.fullmatch(field.pattern, value), (field.pattern, value)
                if field.max_length is not None and isinstance(value, str):
                    assert len(value) <= field.max_length
                if isinstance(value, int | float):
                    assert field.min is None or value >= field.min
                    assert field.max is None or value <= field.max


def test_one_to_one_relations_refer_to_distinct_records(definition: AppDefinition) -> None:
    data = mock_data(definition)
    for name, entity in definition.entities.items():
        for relation_name, relation in entity.relations.items():
            if relation.kind == "one_to_one":
                targets = [r[relation_name] for r in data[name] if r[relation_name] is not None]
                assert len(set(targets)) == len(targets)


def test_an_entity_sets_the_number_of_records_with_an_extension_key() -> None:
    definition = load_definition_text(
        "version: 0\napp: { name: a, title: A }\n"
        "entities:\n  Note:\n    x-mock-count: 3\n    fields: { text: { type: text } }\n"
    )
    assert len(mock_data(definition)["Note"]) == 3


def test_the_records_use_the_keys_of_the_typescript_types(definition: AppDefinition) -> None:
    records = mock_records(definition)
    for name, entity in definition.entities.items():
        keys = {"id"} | {m.key for m in members(name, entity)}
        assert all(set(record) == keys for record in records[name]), name


def test_a_key_field_comes_from_the_name_of_the_record() -> None:
    definition = load_definition(EXAMPLES / "project-tracker" / "app.yaml")
    for record in mock_data(definition)["Project"]:
        initials = "".join(word[0] for word in record["name"].split())
        assert record["key"] == initials, (record["name"], record["key"])


def test_a_derived_value_keeps_the_pattern_and_the_unique_rule() -> None:
    definition = load_definition_text(
        "version: 0\napp: { name: a, title: A }\n"
        "entities:\n  Team:\n    x-mock-count: 16\n    fields:\n"
        "      name: { type: string, required: true }\n"
        "      code: { type: string, required: true, unique: true, pattern: '^[A-Z]{3,4}$' }\n"
        "      slug: { type: string, required: true, pattern: '^[a-z-]+$' }\n"
    )
    records = mock_data(definition)["Team"]
    codes = [record["code"] for record in records]
    assert len(set(codes)) == len(codes)
    for record in records:
        assert re.fullmatch("[A-Z]{3,4}", record["code"])
        words = record["name"].split()
        assert record["code"].startswith(words[0][:2].upper())
        assert record["slug"] == "-".join(words).lower()


def test_a_derived_field_without_a_source_field_gets_a_random_value() -> None:
    definition = load_definition(EXAMPLES / "edge-cases" / "app.yaml")
    codes = [record["code"] for record in mock_data(definition)["Sample"]]
    assert all(re.fullmatch("[A-Z0-9-]+", code) for code in codes)
