from pathlib import Path
from textwrap import dedent

import pytest

from appgen.dsl import (
    App,
    AppDefinition,
    DefinitionError,
    Diagnostic,
    Entity,
    Field,
    Location,
    Operation,
    Page,
    Relation,
    load_definition,
    load_definition_text,
)

VALID = dedent(
    """\
    version: 0
    app:
      name: project-tracker
      title: Project Tracker
    entities:
      Project:
        display_field: name
        fields:
          name: { type: string, required: true, max_length: 120 }
          status: { type: enum, values: [planned, done], default: planned }
        relations:
          tasks: { kind: one_to_many, target: Task, inverse: project }
      Task:
        fields:
          title: { type: string, required: true }
          estimate: { type: decimal, min: 0, precision: 6, scale: 2 }
        relations:
          project: { kind: many_to_one, target: Project, required: true, on_delete: cascade }
    operations:
      list_tasks: { kind: list, entity: Task }
      complete_task:
        kind: custom
        entity: Task
        params:
          note: { type: text }
        returns: Task
    pages:
      projects: { path: /projects, title: Projects, entity: Project }
    """
)


def load(text: str) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def errors(text: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(text)
    return caught.value.diagnostics


def test_loads_the_app() -> None:
    definition = load(VALID)

    assert definition.version == 0
    assert isinstance(definition.app, App)
    assert definition.app.name == "project-tracker"
    assert definition.app.title == "Project Tracker"


def test_loads_entities_in_source_order() -> None:
    definition = load(VALID)

    assert list(definition.entities) == ["Project", "Task"]
    assert isinstance(definition.entities["Project"], Entity)
    assert definition.entities["Project"].display_field == "name"


def test_loads_fields() -> None:
    fields = load(VALID).entities["Project"].fields

    assert list(fields) == ["name", "status"]
    assert isinstance(fields["name"], Field)
    assert fields["name"].type == "string"
    assert fields["name"].required is True
    assert fields["name"].max_length == 120
    assert fields["status"].values == ["planned", "done"]
    assert fields["status"].default == "planned"


def test_loads_relations() -> None:
    relation = load(VALID).entities["Task"].relations["project"]

    assert isinstance(relation, Relation)
    assert relation.kind == "many_to_one"
    assert relation.target == "Project"
    assert relation.on_delete == "cascade"


def test_loads_operations() -> None:
    operations = load(VALID).operations

    assert isinstance(operations["list_tasks"], Operation)
    assert operations["list_tasks"].returns == "none"
    assert operations["complete_task"].kind == "custom"
    assert operations["complete_task"].params["note"].type == "text"
    assert operations["complete_task"].returns == "Task"


def test_loads_pages() -> None:
    page = load(VALID).pages["projects"]

    assert isinstance(page, Page)
    assert page.path == "/projects"
    assert page.entity == "Project"


def test_each_element_keeps_its_location() -> None:
    definition = load(VALID)

    assert definition.location == Location("app.yaml", 1, 1)
    assert definition.app.location == Location("app.yaml", 2, 1)
    assert definition.entities["Project"].location == Location("app.yaml", 6, 3)
    assert definition.entities["Project"].fields["name"].location == Location("app.yaml", 9, 7)
    assert definition.entities["Task"].relations["project"].location == Location("app.yaml", 18, 7)
    assert definition.operations["complete_task"].params["note"].location == Location(
        "app.yaml", 25, 7
    )
    assert definition.pages["projects"].location == Location("app.yaml", 28, 3)


def test_loads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(VALID, encoding="utf-8")

    definition = load_definition(path)

    assert definition.app.location == Location(str(path), 2, 1)


def test_empty_definition_is_an_error() -> None:
    [diagnostic] = errors("")

    assert diagnostic.code == "empty-definition"


def test_root_must_be_a_mapping() -> None:
    [diagnostic] = errors("- a\n")

    assert diagnostic.code == "invalid-value"
    assert diagnostic.message == "Expected a mapping."


def test_missing_key_points_to_the_parent() -> None:
    diagnostics = errors(VALID.replace("  title: Project Tracker\n", ""))

    assert [(d.code, d.message, d.location.line) for d in diagnostics] == [
        ("missing-key", "The key 'title' is missing.", 2)
    ]


def test_unknown_key_shows_its_location_and_a_hint() -> None:
    [diagnostic] = errors(VALID.replace("display_field: name", "display_feld: name"))

    assert diagnostic.code == "unknown-key"
    assert diagnostic.location == Location("app.yaml", 7, 5)
    assert diagnostic.hint == "Did you mean 'display_field'?"


def test_unknown_field_type_shows_a_hint() -> None:
    [diagnostic] = errors(VALID.replace("type: text", "type: txt"))

    assert diagnostic.code == "invalid-value"
    assert diagnostic.location == Location("app.yaml", 25, 21)
    assert diagnostic.hint == "Did you mean 'text'?"


def test_invalid_entity_name_points_to_the_key() -> None:
    [diagnostic] = errors(VALID.replace("  Task:\n", "  task:\n"))

    assert diagnostic.code == "invalid-name"
    assert diagnostic.location == Location("app.yaml", 13, 3)


def test_values_are_strict() -> None:
    [diagnostic] = errors(VALID.replace("required: true, max", 'required: "yes", max'))

    assert diagnostic.message == "Expected true or false."


def test_reports_all_errors_in_one_run() -> None:
    text = VALID.replace("name: project-tracker", "name: Project").replace(
        "kind: list", "kind: lst"
    )

    assert [d.location.line for d in errors(text)] == [3, 20]


def test_entity_needs_one_or_more_fields() -> None:
    text = VALID.replace(
        "Project:\n    display_field: name\n", "Empty:\n    fields: {}\n  Project:\n"
    )

    [diagnostic] = errors(text)

    assert diagnostic.message == "Expected one or more items."


def test_a_yaml_1_1_boolean_in_an_enum_asks_for_quotes() -> None:
    text = VALID.replace("values: [planned, done], default: planned", "values: [planned, on, No]")

    [first, second] = errors(text)

    assert first.code == "invalid-value"
    assert first.message == "YAML reads 'on' as a boolean (true), but a string must be here."
    assert first.hint == 'Put the value in quotes: "on".'
    assert first.location == Location("app.yaml", 10, 47)
    assert second.message == "YAML reads 'No' as a boolean (false), but a string must be here."


def test_a_boolean_in_quotes_or_where_a_boolean_must_be_is_no_error() -> None:
    text = VALID.replace("values: [planned, done], default: planned", 'values: [planned, "on"]')

    assert load(text).entities["Project"].fields["status"].values == ["planned", "on"]
