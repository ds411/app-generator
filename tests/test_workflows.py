from pathlib import Path
from textwrap import dedent

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.gen.generator import generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Task:
        fields:
          title: { type: string, required: true }
          status: { type: enum, values: [open, active, done] }
    """
)

WORKFLOW = dedent(
    """\
    workflows:
      task_status:
        entity: Task
        field: status
        initial: open
        transitions:
          start: { from: [open], to: active }
          finish: { from: [open, active], to: done }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_a_workflow_is_valid_and_allows_its_transitions() -> None:
    definition = load_definition_text(BASE + WORKFLOW, "app.yaml")
    assert validate_definition(definition) == []
    workflow = definition.workflows["task_status"]
    assert workflow.allows("open", "done")
    assert workflow.allows("done", "done")
    assert not workflow.allows("done", "open")
    assert definition.find("workflows.task_status.transitions.finish") is not None


def test_a_workflow_uses_an_enum_field_and_its_values() -> None:
    assert codes(BASE + WORKFLOW.replace("field: status", "field: title")) == [
        ("unsuitable-field", "workflows.task_status")
    ]
    assert codes(BASE + WORKFLOW.replace("entity: Task", "entity: Tsk")) == [
        ("unknown-reference", "workflows.task_status")
    ]
    text = WORKFLOW.replace("initial: open", "initial: new").replace("to: active", "to: closed")
    assert codes(BASE + text) == [
        ("unknown-reference", "workflows.task_status"),
        ("unknown-reference", "workflows.task_status.transitions.start"),
    ]
    assert codes(BASE + WORKFLOW.replace("to: active", "to: open")) == [
        ("invalid-value", "workflows.task_status.transitions.start")
    ]


def test_each_binding_checks_the_transitions() -> None:
    definition = load_definition(EXAMPLE)
    for binding in (fastapi.BINDING, nextjs.BINDING, react.BINDING):
        result = generate(definition, binding)
        assert not [g for g in result.gaps if g.kind in ("workflow", "transition")]
        traced = "\n".join(f.content for f in result.files)
        assert "@trace workflows.booking_status.transitions.confirm" in traced
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    repository = files["app/features/bookings/repository.py"]
    assert '        ("requested", "confirmed"),  # @trace' in repository
    assert "    check_workflows(record, before)\n" in repository
    assert "tests/features/bookings/test_booking_status_workflow.py" in files
