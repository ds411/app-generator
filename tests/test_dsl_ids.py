from textwrap import dedent

import pytest

from appgen.dsl import AppDefinition, DefinitionError, Entity, Field, load_definition_text
from appgen.dsl.ids import element_id, index_elements

DEFINITION = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Project:
        fields:
          name: { type: string }
      Task:
        fields:
          title: { type: string }
        relations:
          project: { kind: many_to_one, target: Project }
    operations:
      complete_task:
        kind: custom
        entity: Task
        params:
          note: { type: text }
    pages:
      tasks: { path: /tasks, title: Tasks }
    """
)


def load(text: str = DEFINITION) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def test_element_id_joins_the_path_with_dots() -> None:
    assert element_id(("entities", "Task", "fields", "title")) == "entities.Task.fields.title"


def test_each_element_has_its_path_as_id() -> None:
    definition = load()

    assert list(definition.elements) == [
        "app",
        "entities.Project",
        "entities.Project.fields.name",
        "entities.Task",
        "entities.Task.fields.title",
        "entities.Task.relations.project",
        "operations.complete_task",
        "operations.complete_task.params.note",
        "pages.tasks",
    ]
    assert definition.entities["Task"].fields["title"].id == "entities.Task.fields.title"
    assert definition.id == ""


def test_model_finds_an_element_by_its_id() -> None:
    definition = load()

    assert (
        definition.find("entities.Task.relations.project")
        is (definition.entities["Task"].relations["project"])
    )
    assert definition.find("entities.Task.fields.missing") is None


def test_a_new_element_does_not_change_other_ids() -> None:
    before = load()
    after = load(
        DEFINITION.replace(
            "  Project:\n", "  Person:\n    fields:\n      email: { type: email }\n  Project:\n"
        ).replace(
            "        fields:\n          title:",
            "        fields:\n          done: { type: boolean }\n          title:",
        )
    )

    for id_, element in before.elements.items():
        found = after.find(id_)
        assert found is not None
        assert type(found) is type(element)
    assert after.find("entities.Person.fields.email") is not None


def test_two_elements_with_the_same_id_report_both_locations() -> None:
    text = DEFINITION.replace(
        "  Task:\n", "  Task:\n    fields: { a: { type: string } }\n  Task:\n", 1
    )

    with pytest.raises(DefinitionError) as caught:
        load(text)

    [diagnostic] = caught.value.diagnostics
    assert diagnostic.code == "duplicate-key"
    assert str(diagnostic.location) == "app.yaml:9:3"
    assert diagnostic.hint == "The first occurrence is at app.yaml:7:3."


def test_index_reports_duplicate_ids_with_both_locations() -> None:
    definition = load()
    # A name with a dot cannot come from YAML, but it can come from code.
    clash = Entity(fields={"x": Field(type="string")})
    clash._location = definition.entities["Project"].location  # pyright: ignore[reportPrivateUsage]
    definition.entities["Task.fields.title"] = clash

    with pytest.raises(DefinitionError) as caught:
        index_elements(definition)

    [diagnostic] = caught.value.diagnostics
    assert diagnostic.code == "duplicate-id"
    assert diagnostic.element_id == "entities.Task.fields.title"
    assert str(diagnostic.location) == "app.yaml:4:3"
    assert diagnostic.hint == "The other element is at app.yaml:9:7."


def test_load_errors_name_the_element() -> None:
    with pytest.raises(DefinitionError) as caught:
        load(DEFINITION.replace("note: { type: text }", "note: { type: txt }"))

    assert caught.value.diagnostics[0].element_id == "operations.complete_task.params.note"
