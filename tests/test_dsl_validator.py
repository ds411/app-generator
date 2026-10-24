from pathlib import Path
from textwrap import dedent

import pytest

from appgen.dsl import (
    DefinitionError,
    Diagnostic,
    check_file,
    load_definition_text,
    validate_definition,
)

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Project:
        display_field: name
        fields:
          name: { type: string, required: true, max_length: 80 }
        relations:
          tasks: { kind: one_to_many, target: Task, inverse: project }
      Task:
        fields:
          title: { type: string }
          status: { type: enum, values: [open, done], default: open }
          estimate: { type: decimal, min: 0, max: 100, precision: 5, scale: 2 }
        relations:
          project: { kind: many_to_one, target: Project, required: true, inverse: tasks }
    operations:
      create_task: { kind: create, entity: Task }
      close_task:
        kind: custom
        entity: Task
        params:
          reason: { type: text }
        returns: Task
    pages:
      tasks: { path: /tasks, title: Tasks, entity: Task }
    """
)


def check(text: str) -> list[Diagnostic]:
    return validate_definition(load_definition_text(text, "app.yaml"))


def codes(text: str) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in check(text)]


def test_valid_definition_has_no_diagnostics() -> None:
    assert check(BASE) == []


def test_names_differ_in_more_than_case() -> None:
    text = BASE.replace("  Task:\n", "  TASK:\n    fields: { x: { type: string } }\n  Task:\n")

    [diagnostic] = check(text)

    assert diagnostic.code == "duplicate-name"
    assert diagnostic.element_id == "entities.Task"
    assert diagnostic.hint == "The other entity is at app.yaml:10:3."


def test_field_and_relation_share_one_scope() -> None:
    text = BASE.replace("      title: { type: string }", "      project: { type: string }")

    assert codes(text) == [("duplicate-name", "entities.Task.relations.project")]


def test_id_is_a_reserved_name() -> None:
    text = BASE.replace("      title: { type: string }", "      id: { type: uuid }")

    assert codes(text) == [("reserved-name", "entities.Task.fields.id")]


def test_field_must_not_clash_with_a_foreign_key() -> None:
    text = BASE.replace("      title: { type: string }", "      project_id: { type: uuid }")

    assert codes(text) == [("duplicate-name", "entities.Task.fields.project_id")]


def test_page_paths_are_unique() -> None:
    text = BASE + "  all_tasks: { path: /tasks, title: All tasks }\n"

    assert codes(text) == [("duplicate-path", "pages.all_tasks")]


def test_relation_target_must_exist() -> None:
    text = BASE.replace("target: Project, required", "target: Projekt, required")

    [diagnostic] = check(text)

    assert diagnostic.code == "unknown-reference"
    assert diagnostic.message == "The entity 'Projekt' does not exist."
    assert diagnostic.element_id == "entities.Task.relations.project"
    assert str(diagnostic.location) == "app.yaml:16:45"
    assert diagnostic.hint == "Did you mean 'Project'?"


def test_operation_entity_and_return_must_exist() -> None:
    text = BASE.replace("kind: create, entity: Task", "kind: create, entity: Tsk").replace(
        "returns: Task", "returns: Tasks"
    )

    assert codes(text) == [
        ("unknown-reference", "operations.create_task"),
        ("unknown-reference", "operations.close_task"),
    ]


def test_page_entity_and_display_field_must_exist() -> None:
    text = BASE.replace("title: Tasks, entity: Task", "title: Tasks, entity: Person").replace(
        "display_field: name", "display_field: title"
    )

    assert codes(text) == [
        ("unknown-reference", "entities.Project"),
        ("unknown-reference", "pages.tasks"),
    ]


def test_one_to_many_needs_an_inverse() -> None:
    text = BASE.replace(", inverse: project }", " }")

    [diagnostic] = check(text)

    assert diagnostic.code == "missing-inverse"
    assert diagnostic.hint is not None


def test_inverse_must_exist_and_match() -> None:
    missing = BASE.replace("inverse: project }", "inverse: projects }")
    wrong_kind = BASE.replace(
        "project: { kind: many_to_one, target: Project, required: true, inverse: tasks }",
        "project: { kind: one_to_one, target: Project, inverse: tasks }",
    )

    assert codes(missing) == [("unknown-reference", "entities.Project.relations.tasks")]
    assert codes(wrong_kind) == [
        ("invalid-inverse", "entities.Project.relations.tasks"),
        ("invalid-inverse", "entities.Task.relations.project"),
    ]


def test_relation_options_fit_the_kind() -> None:
    text = BASE.replace(
        "target: Task, inverse: project }", "target: Task, inverse: project, required: true }"
    ).replace(
        "required: true, inverse: tasks", "required: true, on_delete: set_null, inverse: tasks"
    )

    assert codes(text) == [
        ("invalid-option", "entities.Project.relations.tasks"),
        ("invalid-option", "entities.Task.relations.project"),
    ]


def test_params_and_returns_are_only_for_custom_operations() -> None:
    text = BASE.replace("kind: create, entity: Task", "kind: create, entity: Task, returns: Task")

    assert codes(text) == [("invalid-option", "operations.create_task")]


def test_field_options_fit_the_type() -> None:
    text = BASE.replace(
        "      title: { type: string }", "      title: { type: boolean, max_length: 3 }"
    )

    [diagnostic] = check(text)

    assert diagnostic.message == (
        "'max_length' is not an option of the type 'boolean'. "
        "It is for 'email', 'string', 'text', 'url'."
    )


def test_enum_needs_unique_values() -> None:
    no_values = BASE.replace("type: enum, values: [open, done], default: open", "type: enum")
    duplicates = BASE.replace("values: [open, done]", "values: [open, open]")

    assert codes(no_values) == [("missing-key", "entities.Task.fields.status")]
    assert codes(duplicates) == [("duplicate-name", "entities.Task.fields.status")]


def test_ranges_must_be_in_order() -> None:
    text = BASE.replace(
        "min: 0, max: 100, precision: 5, scale: 2", "min: 9, max: 1, precision: 2, scale: 5"
    )

    assert [d.message for d in check(text)] == [
        "'min' must not be greater than 'max'.",
        "'scale' must not be greater than 'precision'.",
    ]


def test_pattern_must_compile() -> None:
    text = BASE.replace(
        "      title: { type: string }", "      title: { type: string, pattern: '[a-' }"
    )

    assert codes(text) == [("invalid-value", "entities.Task.fields.title")]


def test_default_must_fit_the_type() -> None:
    cases = {
        "{ type: string, default: 3 }": False,
        "{ type: integer, default: true }": False,
        "{ type: integer, default: 3 }": True,
        "{ type: decimal, default: 2.5 }": True,
        "{ type: boolean, default: false }": True,
        "{ type: date, default: '2026-13-01' }": False,
        "{ type: date, default: '2026-10-23' }": True,
        "{ type: datetime, default: '2026-10-23T10:00:00+00:00' }": True,
        "{ type: uuid, default: not-a-uuid }": False,
        "{ type: json, default: { a: 1 } }": True,
    }
    for field, valid in cases.items():
        text = BASE.replace("      title: { type: string }", f"      title: {field}")
        assert (codes(text) == []) is valid, field


def test_enum_default_must_be_a_value() -> None:
    [diagnostic] = check(BASE.replace("default: open", "default: closed"))

    assert diagnostic.hint == "Use one of ['open', 'done']."


def test_params_cannot_be_unique() -> None:
    text = BASE.replace("reason: { type: text }", "reason: { type: text, unique: true }")

    assert codes(text) == [("invalid-option", "operations.close_task.params.reason")]


def test_reports_all_errors_in_one_run_in_source_order() -> None:
    text = (
        BASE.replace("target: Task, inverse", "target: Tsk, inverse")
        .replace("title: Tasks, entity: Task", "title: Tasks, entity: Person")
        .replace("      title: { type: string }", "      id: { type: string }")
    )

    assert [d.location.line for d in check(text)] == [9, 12, 26]


def test_check_file_returns_load_errors(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text("version: 0\n", encoding="utf-8")

    definition, diagnostics = check_file(path)

    assert definition is None
    assert [d.code for d in diagnostics] == ["missing-key", "missing-key"]


def test_check_file_returns_validation_errors(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(BASE.replace("display_field: name", "display_field: x"), encoding="utf-8")

    definition, diagnostics = check_file(path)

    assert definition is not None
    assert [d.code for d in diagnostics] == ["unknown-reference"]


def test_a_field_format_must_suit_the_field_type() -> None:
    estimate = "estimate: { type: decimal, min: 0, max: 100, precision: 5, scale: 2 }"
    with_format = estimate.replace("scale: 2 }", "scale: 2, format: currency }")
    assert codes(BASE.replace(estimate, with_format)) == []

    text = BASE.replace("title: { type: string }", "title: { type: string, format: currency }")
    [diagnostic] = check(text)

    assert diagnostic.code == "invalid-option"
    assert diagnostic.element_id == "entities.Task.fields.title"
    assert diagnostic.message == (
        "The format 'currency' does not suit the type 'string'. It is for 'decimal', 'integer'."
    )
    assert diagnostic.location.line == 12


def test_an_unknown_field_format_is_an_error() -> None:
    text = BASE.replace("title: { type: string }", "title: { type: string, format: money }")

    with pytest.raises(DefinitionError) as error:
        load_definition_text(text, "app.yaml")

    [diagnostic] = error.value.diagnostics
    assert diagnostic.code == "invalid-value"
    assert diagnostic.location.line == 12


def test_the_regions_of_a_page_are_unique_and_have_the_content() -> None:
    page = "tasks: { path: /tasks, title: Tasks, entity: Task }"
    for regions, message in (
        ("[title, title, content]", "Give each region one time only."),
        ("[title, actions]", "The regions must have 'content'."),
    ):
        hint = page.replace(" }", f", arrangement: {{ regions: {regions} }} }}")
        with pytest.raises(DefinitionError) as error:
            load_definition_text(BASE.replace(page, hint), "app.yaml")
        [diagnostic] = error.value.diagnostics
        assert (diagnostic.message, diagnostic.element_id) == (message, "pages.tasks.arrangement")


def test_the_responsive_hint_of_a_board_needs_a_breakpoint_token() -> None:
    board = (
        "ui:\n  views:\n    board:\n      kind: board\n      entity: Task\n      group_by: status\n"
        "      responsive: { below: md, layout: stack }\n"
    )

    assert codes(BASE + board) == [("unknown-reference", "ui.views.board.responsive")]


def test_only_a_page_action_has_a_placement_and_the_top_bar_must_exist() -> None:
    page = "tasks: { path: /tasks, title: Tasks, entity: Task }"
    action = "{ kind: custom, label: Export, placement: topbar }"
    with_action = page.replace(" }", f", actions: {{ export: {action} }} }}")
    text = BASE.replace(page, with_action)
    shell = "ui:\n  layouts:\n    shell:\n      sidebar: {}\n  defaults: { layout: shell }\n"

    assert codes(text) == [("invalid-option", "pages.tasks.actions.export")]
    assert codes(text + shell) == [("invalid-option", "pages.tasks.actions.export")]
    assert codes(text + shell.replace("sidebar: {}", "topbar: {}")) == []
    assert codes(text.replace("placement: topbar", "placement: page")) == []

    view = (
        "ui:\n  views:\n    list:\n      kind: table\n      entity: Task\n"
        "      columns: { title: {} }\n"
        f"      actions:\n        export: {action}\n"
    )
    [diagnostic] = check(BASE + view)
    assert (diagnostic.code, diagnostic.message) == (
        "invalid-option",
        "Only a page action has 'placement'.",
    )


def test_an_operation_action_cannot_run_a_custom_operation_with_params() -> None:
    page = "tasks: { path: /tasks, title: Tasks, entity: Task }"
    action = "{ kind: operation, operation: close_task }"
    text = BASE.replace(page, page.replace(" }", f", actions: {{ close: {action} }} }}"))

    [diagnostic] = check(text)
    assert (diagnostic.code, diagnostic.element_id) == (
        "unsuitable-operation",
        "pages.tasks.actions.close",
    )
    assert diagnostic.hint is not None and "form action" in diagnostic.hint
    # Without params, an action can run the operation.
    assert check(text.replace("    params:\n      reason: { type: text }\n", "")) == []


def test_a_currency_field_gives_an_iso_4217_code() -> None:
    estimate = "estimate: { type: decimal, min: 0, max: 100, precision: 5, scale: 2 }"
    euro = estimate.replace("scale: 2 }", "scale: 2, format: currency, currency: EUR }")
    assert codes(BASE.replace(estimate, euro)) == []

    [diagnostic] = check(BASE.replace(estimate, euro.replace("EUR", "EUX")))
    assert diagnostic.code == "invalid-value"
    assert diagnostic.element_id == "entities.Task.fields.estimate"
    assert diagnostic.message == "'EUX' is not an ISO 4217 currency code."
    assert diagnostic.hint == "Use the code of an active currency, for example 'EUR' or 'USD'."

    text = BASE.replace("title: { type: string }", "title: { type: string, currency: EUR }")
    assert codes(text) == [("invalid-option", "entities.Task.fields.title")]


def test_a_currency_code_has_three_capital_letters() -> None:
    text = BASE.replace("title: { type: string }", "title: { type: integer, currency: eur }")

    with pytest.raises(DefinitionError) as error:
        load_definition_text(text, "app.yaml")

    [diagnostic] = error.value.diagnostics
    assert diagnostic.location.line == 12
