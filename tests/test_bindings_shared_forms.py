"""Tests of the form plans that the shared form templates read."""

from pathlib import Path

import pytest

from appgen.bindings.shared.forms import FormContext, form_rules
from appgen.bindings.shared.views import ViewContext
from appgen.dsl import load_definition

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"
FORMS = Path(__file__).parent / "fixtures" / "react-forms.yaml"


@pytest.fixture(scope="module")
def forms() -> FormContext:
    return FormContext(load_definition(FORMS))


def test_the_context_lists_the_forms_widgets_and_relations(forms: FormContext) -> None:
    assert forms.names[:2] == ["new_book", "edit_book"]
    assert {"radio", "date", "datetime", "relation", "custom"} <= forms.widgets
    assert forms.relations


def test_a_form_picks_its_fields_from_the_schema_of_its_operation(forms: FormContext) -> None:
    assert forms.plan("edit_book").schema == (
        "bookPatchSchema.pick({ title: true, format: true, shelfId: true })"
    )
    assert forms.plan("new_book").call == "createBook(input as BookInput)"
    assert forms.plan("edit_book").call == "updateBook(record.id, input)"
    lend = forms.plan("lend_book")
    assert lend.schema.startswith("lendBookParamsSchema.pick({ reader: true,")
    assert lend.call == "lendBook(record.id, input as LendBookParams)"


def test_the_mode_of_a_form_follows_its_definition_and_its_page(forms: FormContext) -> None:
    modes = {name: forms.plan(name).mode for name in forms.names}
    assert modes["new_book"] == "page"
    assert modes["quick_edit"] == "sheet"
    assert modes["lend_book"] == "dialog"
    assert forms.plan("new_book").page_href == 'pageHref("newBook")'
    assert forms.plan("edit_book").page_href == 'pageHref("editBook", { id: record.id })'
    assert forms.plan("shelf_book").route_params


def test_each_field_has_its_widget_type_and_rules(forms: FormContext) -> None:
    fields = {f.name: f for f in forms.plan("new_book").fields}
    assert fields["format"].value_type == '("paper" | "hard" | "ebook") | null'
    assert fields["authors"].kind == "many"
    assert fields["authors"].value_type == "string[]"
    assert fields["extra"].value_type == "unknown"
    assert fields["title"].classes == "col-span-2 max-md:col-span-1"
    assert [c.condition for c in fields["pages"].checks] == [
        "values.pages !== null && values.pages < 1",
        "values.pages !== null && values.pages > 5000",
    ]


def test_the_form_rules_compare_fields_or_call_their_gaps(forms: FormContext) -> None:
    [compare] = forms.plan("new_book").rules
    assert compare.condition == '!compareRule(values.receivedAt, "gte", values.published)'
    assert [r.gap_name for r in forms.plan("quick_book").rules] == ["uniqueTitleRule", "wholeRule"]
    assert forms.plan("new_book").navigate == 'pageHref("book", { id: result.id })'


def test_a_view_opens_its_forms_only_if_the_binding_generates_them() -> None:
    definition = load_definition(EXAMPLE)
    with_forms = ViewContext(definition, forms=True).view_plan("project_table")
    assert [f.component for f in with_forms.forms] == ["NewProjectForm", "EditProjectForm"]
    assert ViewContext(definition).view_plan("project_table").forms == []


def test_the_form_rules_write_the_shared_runtime_files_once() -> None:
    paths = [rule.path for rule in form_rules()]
    assert "src/shared/lib/form.ts" in paths
    format_rule = next(r for r in form_rules() if r.path == "src/shared/lib/format.ts")
    assert format_rule.when == "ui_forms.names and not ui_views.list_views"


def test_a_number_field_with_a_format_shows_the_formatted_value() -> None:
    forms = FormContext(load_definition(EXAMPLE))
    fields = {f.name: f for f in forms.plan("new_project").fields}
    assert fields["budget"].format == "currency"
    assert fields["name"].format is None
    assert "number_format" in forms.widgets
