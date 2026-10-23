from dataclasses import replace
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.dsl import load_definition_text
from appgen.dsl.ui import TokenGroup
from appgen.gen import (
    Binding,
    Gap,
    Output,
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


def test_element_kinds_of_dsl_v0() -> None:
    kinds = {e.id: e.kind for e in iter_elements(DEFINITION)}
    assert kinds["app"] == "app"
    assert kinds["entities.Task"] == "entity"
    assert kinds["entities.Task.fields.title"] == "field"
    assert kinds["entities.Task.relations.project"] == "relation"
    assert kinds["operations.complete_task"] == "operation"
    assert kinds["operations.complete_task.params.note"] == "param"
    assert kinds["pages.projects"] == "page"


def test_element_kind_is_the_class_name_in_snake_case() -> None:
    group = TokenGroup.model_validate({"blue": {"$value": "#2563eb"}})
    assert element_kind(("ui", "tokens", "color"), group) == "token_group"
    assert element_kind(("ui", "tokens", "color", "blue"), group.children["blue"]) == "token"


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
    assert [f.path for f in entity_files] == ["entities/Project.md", "entities/Task.md"]
    assert "- name: string (required) <!--" in entity_files[0].content


def test_elements_of_uncovered_kinds_are_gaps(minimal: Binding) -> None:
    result = generate(DEFINITION, minimal)
    assert [(g.element_id, g.kind) for g in result.gaps] == [
        ("entities.Project.relations.tasks", "relation"),
        ("entities.Task.relations.project", "relation"),
        ("operations.complete_task", "operation"),
        ("operations.complete_task.params.note", "param"),
        ("pages.projects", "page"),
    ]


def test_a_binding_without_a_gap_rule_only_lists_the_gaps(minimal: Binding) -> None:
    result = generate(DEFINITION, replace(minimal, gap_rule=None))
    assert result.gaps[0] == Gap("entities.Project.relations.tasks", "relation")
    assert not any(f.kind == "extension" for f in result.files)


def test_a_binding_that_covers_all_kinds_has_no_gaps(minimal: Binding) -> None:
    full = replace(
        minimal,
        covers=frozenset({"app", "entity", "field", "relation", "operation", "param", "page"}),
    )
    assert generate(DEFINITION, full).gaps == []


def _shout(name: str) -> str:
    return repr(name.upper())


def test_templates_can_call_the_helpers_and_the_naming_filters(tmp_path: Path) -> None:
    (tmp_path / "page.ts.j2").write_text(
        "{{ trace_header(element_id) }}\nexport const {{ name | camel }} = {{ shout(name) }};\n"
    )
    binding = Binding(
        name="temp",
        description="A binding for one test.",
        template_dir=tmp_path,
        outputs=(Output(template="page.ts.j2", path="{{ name | kebab }}.ts", for_each="page"),),
        covers=frozenset({"page"}),
        helpers={"shout": _shout},
    )

    result = generate(DEFINITION, binding)

    assert result.files[0].path == "projects.ts"
    assert "export const projects = 'PROJECTS';" in result.files[0].content
