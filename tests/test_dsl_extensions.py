from textwrap import dedent

import pytest

from appgen.dsl import AppDefinition, DefinitionError, Diagnostic, load_definition_text
from appgen.dsl.model import RESERVED_SECTIONS

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Task:
        fields:
          title: { type: string }
    """
)


def load(text: str) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def errors(text: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(text)
    return caught.value.diagnostics


def test_missing_version_is_reported() -> None:
    [diagnostic] = errors(BASE.replace("version: 0\n", ""))

    assert diagnostic.code == "missing-version"
    assert str(diagnostic.location) == "app.yaml:1:1"
    assert diagnostic.hint == "Add 'version: 0' at the top of the file."


def test_unknown_version_is_reported() -> None:
    [diagnostic] = errors(BASE.replace("version: 0", "version: 2"))

    assert diagnostic.code == "unsupported-version"
    assert diagnostic.message == "The DSL version 2 is not supported."
    assert str(diagnostic.location) == "app.yaml:1:10"


def test_unknown_key_is_reported_with_its_location() -> None:
    [diagnostic] = errors(
        BASE.replace("title: { type: string }", "title: { type: string, size: 3 }")
    )

    assert diagnostic.code == "unknown-key"
    assert diagnostic.message == "The key 'size' is not known here."
    assert str(diagnostic.location) == "app.yaml:6:30"
    assert diagnostic.element_id == "entities.Task.fields.title"


def test_extension_keys_are_kept_without_a_report() -> None:
    text = dedent(
        """\
        version: 0
        x-generator: { owner: team-a }
        app: { name: tracker, title: Tracker, x-icon: kanban }
        entities:
          Task:
            x-table: tasks
            fields:
              title: { type: string, x-widget: { kind: textarea, rows: 3 } }
        """
    )

    definition = load(text)

    assert definition.extensions == {"x-generator": {"owner": "team-a"}}
    assert definition.app.extensions == {"x-icon": "kanban"}
    assert definition.entities["Task"].extensions == {"x-table": "tasks"}
    assert definition.entities["Task"].fields["title"].extensions == {
        "x-widget": {"kind": "textarea", "rows": 3}
    }
    assert definition.entities["Task"].fields["title"].type == "string"


def test_elements_without_extensions_have_none() -> None:
    assert load(BASE).entities["Task"].extensions == {}


def test_extension_key_in_a_mapping_of_names_is_an_error_with_a_hint() -> None:
    text = BASE.replace("entities:\n", "entities:\n  x-note: { fields: { a: { type: string } } }\n")

    [diagnostic] = errors(text)

    assert diagnostic.code == "invalid-name"
    assert diagnostic.hint == "Put extension keys in an element, not in a mapping of names."


@pytest.mark.parametrize("section", RESERVED_SECTIONS)
def test_reserved_sections_are_not_supported_yet(section: str) -> None:
    [diagnostic] = errors(BASE + f"{section}:\n  anything: 1\n")

    assert diagnostic.code == "not-supported"
    assert diagnostic.message == (
        f"The section '{section}' is not supported in this version of the DSL."
    )
    assert str(diagnostic.location) == "app.yaml:7:1"


def test_reserved_sections_are_reported_with_other_errors() -> None:
    diagnostics = errors(BASE.replace("version: 0\n", "") + "auth: {}\n")

    assert [d.code for d in diagnostics] == ["missing-version", "not-supported"]
