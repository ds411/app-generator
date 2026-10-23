from dataclasses import replace
from textwrap import dedent

import pytest

from appgen.dsl import load_definition_text
from appgen.gen import (
    Binding,
    Gap,
    UnknownBindingError,
    available_bindings,
    element_kind,
    find_binding,
    generate,
    iter_elements,
)

DEFINITION = load_definition_text(
    dedent(
        """\
        version: 0
        app: { name: project-tracker, title: Project Tracker }
        entities:
          Project:
            fields:
              name: { type: string, required: true }
            relations:
              tasks: { kind: one_to_many, target: Task, inverse: project }
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
          projects: { path: /projects, title: Projects }
        """
    )
)


@pytest.fixture
def minimal() -> Binding:
    return find_binding("minimal")


def test_find_binding_by_name(minimal: Binding) -> None:
    assert minimal.name == "minimal"
    assert (minimal.template_dir / minimal.outputs[0].template).is_file()
    assert "minimal" in available_bindings()


def test_unknown_binding_lists_the_available_bindings() -> None:
    with pytest.raises(UnknownBindingError, match=r"Available bindings: .*minimal"):
        find_binding("cobol")


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (("app",), "app"),
        (("entities", "Task"), "entity"),
        (("entities", "Task", "fields", "title"), "field"),
        (("entities", "Task", "relations", "project"), "relation"),
        (("operations", "complete_task"), "operation"),
        (("operations", "complete_task", "params", "note"), "param"),
        (("pages", "projects"), "page"),
        (("ui", "layouts", "main"), "layouts"),
    ],
)
def test_element_kind(path: tuple[str, ...], kind: str) -> None:
    assert element_kind(path) == kind


def test_iter_elements_gives_ids_in_source_order() -> None:
    ids = [e.id for e in iter_elements(DEFINITION)]
    assert ids == [
        "app",
        "entities.Project",
        "entities.Project.fields.name",
        "entities.Project.relations.tasks",
        "entities.Task",
        "entities.Task.fields.title",
        "entities.Task.relations.project",
        "operations.complete_task",
        "operations.complete_task.params.note",
        "pages.projects",
    ]


def test_minimal_binding_writes_one_file_for_each_entity(minimal: Binding) -> None:
    result = generate(DEFINITION, minimal)
    entity_files = [f for f in result.files if f.path.startswith("entities/")]
    assert [f.path for f in entity_files] == ["entities/Project.txt", "entities/Task.txt"]
    assert "- name: string (required)\n" in entity_files[0].content


def test_elements_of_uncovered_kinds_are_gaps(minimal: Binding) -> None:
    result = generate(DEFINITION, minimal)
    assert result.gaps == [
        Gap("entities.Project.relations.tasks", "relation"),
        Gap("entities.Task.relations.project", "relation"),
        Gap("operations.complete_task", "operation"),
        Gap("operations.complete_task.params.note", "param"),
        Gap("pages.projects", "page"),
    ]


def test_a_binding_that_covers_all_kinds_has_no_gaps(minimal: Binding) -> None:
    full = replace(
        minimal,
        covers=frozenset({"app", "entity", "field", "relation", "operation", "param", "page"}),
    )
    assert generate(DEFINITION, full).gaps == []
