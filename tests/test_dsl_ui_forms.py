from textwrap import dedent

import pytest
from ui_support import UI_TOKENS

from appgen.dsl import AppDefinition, DefinitionError, Diagnostic, load_definition_text
from appgen.dsl.ui.forms import CompareRule, CustomRule, Form
from appgen.dsl.validator import validate_definition

VALID = (
    dedent(
        """\
    version: 0
    app: { name: demo, title: Demo }
    entities:
      Person:
        display_field: name
        fields:
          name: { type: string }
      Project:
        display_field: name
        fields:
          name: { type: string }
      Task:
        display_field: title
        fields:
          title: { type: string, max_length: 200 }
          description: { type: text }
          status: { type: enum, values: [todo, in_progress, done] }
          priority: { type: enum, values: [low, medium, high] }
          estimate: { type: decimal }
          start_date: { type: date }
          due_date: { type: date }
          done: { type: boolean }
          meta: { type: json }
          reference: { type: url }
        relations:
          project: { kind: many_to_one, target: Project }
          assignee: { kind: many_to_one, target: Person }
          watchers: { kind: many_to_many, target: Person }
    operations:
      create_task: { kind: create, entity: Task }
      update_task: { kind: update, entity: Task }
      delete_task: { kind: delete, entity: Task }
      create_project: { kind: create, entity: Project }
      complete_task:
        kind: custom
        entity: Task
        params:
          note: { type: text }
          notify: { type: boolean }
        returns: Task
    ui:
      forms:
        new_task:
          entity: Task
          operation: create_task
          mode: dialog
          title: New task
          description: Add a task to the project.
          submit_label: Create task
          cancel_label: Cancel
          grid: { columns: 2, gap: "{spacing.4}" }
          sections:
            main: { title: Details, fields: [title, description, status, priority] }
            planning:
              title: Planning
              description: When and by whom.
              fields: [project, assignee, watchers, start_date, due_date, estimate]
          fields:
            title:
              label: Title
              placeholder: What needs to be done?
              help: A short summary.
              span: 2
              rules:
                required: { message: Enter a title. }
                min_length: { value: 3, message: Use 3 or more characters. }
                pattern: { value: "^[^<>]*$", message: Do not use angle brackets. }
            description: { widget: textarea, rows: 4, span: 2 }
            status: { widget: radio }
            priority: {}
            project: { widget: select }
            assignee: { widget: relation, label: Assignee }
            watchers: {}
            start_date: {}
            due_date: { widget: date }
            estimate: { step: 0.5, rules: { min: { value: 0, message: Use 0 or more. } } }
            done: { widget: checkbox }
            meta: { widget: custom }
            reference: { widget: text }
          rules:
            due_after_start:
              kind: compare
              field: due_date
              op: gte
              other: start_date
              message: The due date must be on or after the start date.
            unique_title: { kind: custom, fields: [title] }
          defaults: { project: $route.id, status: todo }
          on_success: { toast: Task created, close: true }
        edit_task:
          entity: Task
          operation: update_task
          mode: sheet
          fields:
            title: {}
            done: { widget: switch }
        complete_task:
          entity: Task
          operation: complete_task
          mode: page
          fields:
            note: { widget: textarea }
            notify: {}
    """
    )
    + UI_TOKENS
)


def load(text: str = VALID) -> AppDefinition:
    return load_definition_text(text, "app.yaml")


def problems(text: str) -> list[tuple[str, str | None, str]]:
    return [(d.code, d.element_id, d.message) for d in validate_definition(load(text))]


def codes(text: str) -> list[tuple[str, str | None]]:
    return [(code, element_id) for code, element_id, _ in problems(text)]


def errors(text: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(text)
    return caught.value.diagnostics


def test_valid_forms_have_no_problems() -> None:
    assert problems(VALID) == []


def test_loads_a_form() -> None:
    ui = load().ui
    assert ui is not None

    form = ui.forms["new_task"]

    assert isinstance(form, Form)
    assert (form.entity, form.operation, form.mode) == ("Task", "create_task", "dialog")
    assert form.submit_label == "Create task"
    assert form.grid is not None
    assert form.grid.columns == 2
    assert list(form.sections) == ["main", "planning"]
    assert form.sections["planning"].fields[0] == "project"
    title = form.fields["title"]
    assert (title.label, title.placeholder, title.help, title.span) == (
        "Title",
        "What needs to be done?",
        "A short summary.",
        2,
    )
    assert title.rules is not None
    assert title.rules.required is not None
    assert title.rules.required.message == "Enter a title."
    assert title.rules.min_length is not None
    assert title.rules.min_length.value == 3
    assert form.fields["description"].rows == 4
    assert form.fields["estimate"].step == 0.5
    assert form.fields["priority"].widget is None
    assert isinstance(form.rules["due_after_start"], CompareRule)
    assert isinstance(form.rules["unique_title"], CustomRule)
    assert form.defaults == {"project": "$route.id", "status": "todo"}
    assert form.on_success is not None
    assert form.on_success.toast == "Task created"


def test_form_elements_have_ids() -> None:
    definition = load()

    assert definition.find("ui.forms.new_task.fields.title") is not None
    assert definition.find("ui.forms.new_task.sections.planning") is not None
    assert definition.find("ui.forms.new_task.rules.due_after_start") is not None


@pytest.mark.parametrize(
    ("old", "new", "code", "element_id"),
    [
        (
            "status: { widget: radio }",
            "status: { widget: switch }",
            "unsuitable-field",
            "ui.forms.new_task.fields.status",
        ),
        (
            "project: { widget: select }",
            "project: { widget: text }",
            "unsuitable-field",
            "ui.forms.new_task.fields.project",
        ),
        (
            "watchers: {}",
            "watchers: { widget: select }",
            "unsuitable-field",
            "ui.forms.new_task.fields.watchers",
        ),
        (
            "estimate: { step: 0.5,",
            "estimate: { widget: date, step: 0.5,",
            "unsuitable-field",
            "ui.forms.new_task.fields.estimate",
        ),
        ("meta: { widget: custom }", "meta: {}", "missing-widget", "ui.forms.new_task.fields.meta"),
        (
            "rules: { min: { value: 0,",
            "rules: { min_length: { value: 0,",
            "unsuitable-field",
            "ui.forms.new_task.fields.estimate.rules",
        ),
        (
            "min_length: { value: 3,",
            "max: { value: 3,",
            "unsuitable-field",
            "ui.forms.new_task.fields.title.rules",
        ),
        ("title: {}\n", "titel: {}\n", "unknown-reference", "ui.forms.edit_task.fields.titel"),
        ("notify: {}", "notice: {}", "unknown-reference", "ui.forms.complete_task.fields.notice"),
        (
            "operation: create_task",
            "operation: create_tsk",
            "unknown-reference",
            "ui.forms.new_task",
        ),
        (
            "operation: update_task",
            "operation: delete_task",
            "unsuitable-operation",
            "ui.forms.edit_task",
        ),
        (
            "operation: update_task",
            "operation: create_project",
            "unsuitable-operation",
            "ui.forms.edit_task",
        ),
        (
            "other: start_date",
            "other: start",
            "unknown-reference",
            "ui.forms.new_task.rules.due_after_start",
        ),
        (
            "fields: [title, description, status, priority]",
            "fields: [title, description, status, prio]",
            "unknown-reference",
            "ui.forms.new_task.sections.main",
        ),
        (
            "fields: [title, description, status, priority]",
            "fields: [title, description, status, priority, estimate]",
            "duplicate-name",
            "ui.forms.new_task.sections.planning",
        ),
        ("project: $route.id", "project: $param.id", "invalid-value", "ui.forms.new_task"),
        ("status: todo }", "state: todo }", "unknown-reference", "ui.forms.new_task"),
    ],
)
def test_form_problems(old: str, new: str, code: str, element_id: str) -> None:
    assert old in VALID

    assert codes(VALID.replace(old, new, 1)) == [(code, element_id)]


def test_unknown_field_of_a_form_gets_a_hint() -> None:
    [diagnostic] = validate_definition(load(VALID.replace("title: {}\n", "titel: {}\n")))

    assert diagnostic.hint == "Did you mean 'title'?"


def test_form_cannot_set_the_primary_key() -> None:
    assert codes(VALID.replace("title: {}\n", "id: {}\n")) == [
        ("unsuitable-field", "ui.forms.edit_task.fields.id")
    ]


def test_unknown_widget_gets_a_hint() -> None:
    [diagnostic] = errors(VALID.replace("widget: checkbox", "widget: chekbox"))

    assert diagnostic.hint == "Did you mean 'checkbox'?"


def test_form_needs_fields() -> None:
    [diagnostic] = errors(
        VALID.replace(
            "fields:\n        note: { widget: textarea }\n        notify: {}\n", "fields: {}\n"
        )
    )

    assert diagnostic.message == "Expected one or more items."


def test_unknown_rule_kind() -> None:
    [diagnostic] = errors(VALID.replace("kind: custom, fields: [title]", "kind: script"))

    assert diagnostic.message == "The kind 'script' is not valid. Expected 'compare', 'custom'."
