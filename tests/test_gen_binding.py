from dataclasses import replace
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from appgen.dsl import AppDefinition, load_definition_text
from appgen.dsl.ui import TokenGroup
from appgen.gen import (
    Binding,
    Gap,
    GenerationError,
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


def _templates(tmp_path: Path, templates: dict[str, str]) -> Path:
    for name, text in templates.items():
        (tmp_path / name).write_text(text, newline="")
    return tmp_path


def test_a_false_condition_skips_the_rule_or_the_element(tmp_path: Path) -> None:
    binding = Binding(
        name="temp",
        description="A binding for one test.",
        template_dir=_templates(tmp_path, {"t.md.j2": "<!-- @trace app file -->\n"}),
        outputs=(
            Output("t.md.j2", "{{ name }}.md", "entity", when="element.relations | length > 0"),
            Output("t.md.j2", "pages.md", when="definition.pages | length > 1"),
            Output("t.md.j2", "custom-{{ name }}.md", "operation", when="element.kind == 'custom'"),
        ),
        covers=frozenset({"entity", "operation"}),
    )
    paths = [f.path for f in generate(DEFINITION, binding).files]
    assert paths == ["Project.md", "Task.md", "custom-complete_task.md"]


def test_a_condition_with_a_missing_value_stops_the_run(tmp_path: Path) -> None:
    binding = Binding(
        name="temp",
        description="A binding for one test.",
        template_dir=_templates(tmp_path, {"t.md.j2": "<!-- @trace app file -->\n"}),
        outputs=(Output("t.md.j2", "t.md", when="no_such_value"),),
        covers=frozenset({"app"}),
    )
    with pytest.raises(GenerationError, match=r"condition of the rule 't\.md\.j2' needs a missing"):
        generate(DEFINITION, binding)


def test_the_binding_context_and_filters_reach_the_templates(tmp_path: Path) -> None:
    def context(definition: AppDefinition) -> dict[str, Any]:
        return {"entity_count": len(definition.entities)}

    def twice(value: int) -> int:
        return value * 2

    binding = Binding(
        name="temp",
        description="A binding for one test.",
        template_dir=_templates(
            tmp_path,
            {"t.md.j2": "<!-- @trace app file -->\n{{ entity_count | twice }}\n"},
        ),
        outputs=(Output("t.md.j2", "t-{{ entity_count }}.md", when="entity_count == 2"),),
        covers=frozenset({"app"}),
        context=context,
        filters={"twice": twice},
    )
    [file] = generate(DEFINITION, binding).files
    assert (file.path, file.content.splitlines()[-1]) == ("t-2.md", "4")


def test_the_binding_context_cannot_replace_a_generator_value(tmp_path: Path) -> None:
    binding = Binding(
        name="temp",
        description="A binding for one test.",
        template_dir=tmp_path,
        outputs=(),
        covers=frozenset({"app"}),
        context=lambda definition: {"tokens": [], "name": "x"},
    )
    with pytest.raises(GenerationError, match="replaces values of the generator: name, tokens"):
        generate(DEFINITION, binding)


def test_elements_of_excluded_kinds_and_under_them_are_not_gaps(minimal: Binding) -> None:
    result = generate(DEFINITION, replace(minimal, excludes=frozenset({"operation", "page"})))

    assert [g.element_id for g in result.gaps] == [
        "entities.Project.relations.tasks",
        "entities.Task.relations.project",
    ]
    assert result.excluded_kinds == ("operation", "page")
