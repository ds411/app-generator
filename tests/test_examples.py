import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from appgen.dsl import check_file
from appgen.dsl.model import FIELD_TYPES, OPERATION_KINDS, RELATION_KINDS
from appgen.dsl.schema import json_schema

EXAMPLES = Path(__file__).parent.parent / "examples"
VALID = sorted(EXAMPLES.glob("*/app.yaml"))
INVALID = sorted((EXAMPLES / "invalid").glob("*.yaml"))

# Each diagnostic code that a YAML file can cause. "file-error" (a file
# that cannot be read) and "duplicate-id" (only from code, see ADR 0002)
# have no example file.
DIAGNOSTIC_CODES = {
    "yaml-syntax",
    "duplicate-key",
    "invalid-key",
    "empty-definition",
    "missing-version",
    "unsupported-version",
    "not-supported",
    "missing-key",
    "unknown-key",
    "invalid-value",
    "invalid-name",
    "duplicate-name",
    "reserved-name",
    "duplicate-path",
    "unknown-reference",
    "invalid-option",
    "missing-inverse",
    "invalid-inverse",
    "invalid-token-value",
    "token-type-mismatch",
    "token-loop",
    "unsuitable-token",
    "unsuitable-field",
    "unsuitable-badge",
    "unsuitable-operation",
    "unsuitable-view",
    "missing-selection",
    "missing-widget",
}


def expected_code(path: Path) -> str:
    match = re.match(r"# expect: ([a-z-]+)", path.read_text(encoding="utf-8"))
    assert match, f"{path.name} must start with '# expect: <code>'."
    return match.group(1)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.parent.name)
def test_valid_examples_load_without_diagnostics(path: Path) -> None:
    definition, diagnostics = check_file(path)

    assert definition is not None
    assert [str(d) for d in diagnostics] == []


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.parent.name)
def test_valid_examples_match_the_json_schema(path: Path) -> None:
    instance = yaml.safe_load(path.read_text(encoding="utf-8"))

    jsonschema.validate(instance, json_schema(), cls=jsonschema.Draft202012Validator)


def test_project_tracker_has_the_planned_content() -> None:
    definition, _ = check_file(EXAMPLES / "project-tracker" / "app.yaml")

    assert definition is not None
    assert {"Project", "Task", "Person"} <= set(definition.entities)
    for entity in ("Project", "Task", "Person"):
        kinds = {op.kind for op in definition.operations.values() if op.entity == entity}
        assert {"create", "read", "update", "delete", "list"} <= kinds, entity
    assert any(op.kind == "custom" for op in definition.operations.values())
    assert definition.entities["Task"].relations["project"].target == "Project"


def test_edge_cases_use_each_field_type_relation_kind_and_operation_kind() -> None:
    definition, _ = check_file(EXAMPLES / "edge-cases" / "app.yaml")

    assert definition is not None
    entities = definition.entities.values()
    field_types = {field.type for entity in entities for field in entity.fields.values()}
    kinds = {relation.kind for entity in entities for relation in entity.relations.values()}
    operations = {operation.kind for operation in definition.operations.values()}
    assert field_types == set(FIELD_TYPES)
    assert kinds == set(RELATION_KINDS)
    assert operations == set(OPERATION_KINDS)


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_examples_give_the_expected_diagnostic(path: Path) -> None:
    definition, diagnostics = check_file(path)

    assert definition is None or diagnostics
    assert expected_code(path) in {d.code for d in diagnostics}
    for diagnostic in diagnostics:
        assert diagnostic.location.file == str(path)
        assert diagnostic.location.line >= 1


def test_invalid_examples_cover_each_diagnostic_code() -> None:
    covered = {expected_code(path) for path in INVALID}

    assert covered >= DIAGNOSTIC_CODES, sorted(DIAGNOSTIC_CODES - covered)
