from pathlib import Path

import pytest

from appgen.dsl import Location
from appgen.dsl.source import YamlError, read_yaml, read_yaml_file


def test_read_yaml_keeps_the_positions_of_keys_and_values() -> None:
    document = read_yaml("a:\n  b: [1, 2]\n", "f.yaml")

    assert document.data == {"a": {"b": [1, 2]}}
    assert document.source_map.keys[("a",)] == Location("f.yaml", 1, 1)
    assert document.source_map.keys[("a", "b")] == Location("f.yaml", 2, 3)
    assert document.source_map.values[("a", "b", 1)] == Location("f.yaml", 2, 10)


def test_read_yaml_keeps_the_text_of_keys() -> None:
    document = read_yaml("on: 1\n2: yes\n")

    assert document.data == {"on": 1, "2": True}


def test_source_map_finds_the_nearest_parent() -> None:
    source_map = read_yaml("a:\n  b: 1\n", "f.yaml").source_map

    assert source_map.element(("a", "b", "c")) == Location("f.yaml", 2, 3)
    assert source_map.value(("a", "b", "c")) == Location("f.yaml", 2, 6)
    assert source_map.element(("x",)) == Location("f.yaml", 1, 1)


def test_read_yaml_returns_none_for_an_empty_document() -> None:
    assert read_yaml("# only a comment\n").data is None


def test_syntax_error_shows_the_file_line_and_column() -> None:
    with pytest.raises(YamlError) as caught:
        read_yaml("a:\n  b: [1, 2\n", "f.yaml")

    [diagnostic] = caught.value.diagnostics
    assert diagnostic.code == "yaml-syntax"
    assert diagnostic.location.file == "f.yaml"
    assert diagnostic.location.line == 3


def test_duplicate_key_is_an_error_with_both_locations() -> None:
    with pytest.raises(YamlError) as caught:
        read_yaml("a: 1\nb: 2\na: 3\n", "f.yaml")

    [diagnostic] = caught.value.diagnostics
    assert diagnostic.code == "duplicate-key"
    assert diagnostic.location == Location("f.yaml", 3, 1)
    assert diagnostic.hint is not None
    assert "f.yaml:1:1" in diagnostic.hint


def test_mapping_key_must_be_a_scalar() -> None:
    with pytest.raises(YamlError) as caught:
        read_yaml("? [a]\n: 1\n")

    assert caught.value.diagnostics[0].code == "invalid-key"


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(YamlError) as caught:
        read_yaml_file(tmp_path / "missing.yaml")

    assert caught.value.diagnostics[0].code == "file-error"
