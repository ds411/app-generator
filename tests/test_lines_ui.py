"""The lines of a record in the front ends, and the lines editor of the forms (ADR 0035)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.bindings.shared.forms import FormContext
from appgen.dsl import AppDefinition, load_definition, load_definition_text, validate_definition
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "totals.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Order:
        fields:
          number: { type: string, required: true }
          total: { type: decimal, scale: 2, computed: sum(lines.amount) }
        relations:
          lines: { kind: one_to_many, target: Line, inverse: order }
          notes: { kind: one_to_many, target: Note, inverse: order }
      Line:
        fields:
          amount: { type: decimal, scale: 2, required: true }
          label: { type: string, translatable: false }
          code: { type: string, required: true, default: X }
          double: { type: decimal, computed: amount * 2 }
          meta: { type: json }
        relations:
          order: { kind: many_to_one, target: Order, required: true, inverse: lines }
          product: { kind: many_to_one, target: Product }
          tags: { kind: many_to_many, target: Product }
      Note:
        fields:
          text: { type: text }
        relations:
          order: { kind: many_to_one, target: Order, required: true, inverse: notes }
      Product:
        display_field: name
        fields:
          name: { type: string }
    operations:
      create_order: { kind: create, entity: Order, lines: [lines] }
      update_order: { kind: update, entity: Order, lines: [lines] }
    ui:
      forms:
        new_order:
          entity: Order
          operation: create_order
          fields:
            number: {}
            lines: {editor}
    """
)

EDITOR = "{ widget: lines, fields: [amount, product] }"


def definition_text(editor: str = EDITOR) -> str:
    """Return the base definition with the form field `lines` of the form `new_order`."""
    return BASE.replace("{editor}", editor)


def problems(text: str) -> list[tuple[str, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.message) for d in validate_definition(definition)]


def files_of(definition: AppDefinition, binding: Binding) -> dict[str, str]:
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_form_edits_the_lines_of_its_operation_with_the_widget_lines() -> None:
    assert problems(definition_text()) == []


@pytest.mark.parametrize(
    ("editor", "expected"),
    [
        (
            "{ widget: lines }",
            [
                (
                    "missing-key",
                    "The widget 'lines' needs 'fields': the fields of the lines, one column each.",
                )
            ],
        ),
        (
            "{ widget: lines, fields: [product] }",
            [
                (
                    "invalid-value",
                    "The lines editor of 'lines' has no column for the required field "
                    "'Line.amount', so a new line has no value for it.",
                )
            ],
        ),
        (
            "{ widget: lines, fields: [amount, amount] }",
            [("duplicate-name", "The names in 'fields' must be unique.")],
        ),
        (
            "{ widget: lines, fields: [amount, order] }",
            [
                (
                    "unsuitable-field",
                    "The column 'order' of the lines 'Line' is the relation to the record, "
                    "which the form sets.",
                )
            ],
        ),
        (
            "{ widget: lines, fields: [amount, double] }",
            [("unsuitable-field", "The column 'double' of the lines 'Line' is computed.")],
        ),
        (
            "{ widget: lines, fields: [amount, tags] }",
            [
                (
                    "unsuitable-field",
                    "The column 'tags' of the lines 'Line' (many_to_many) has no widget in a "
                    "lines editor.",
                )
            ],
        ),
        (
            "{ widget: lines, fields: [amount, meta] }",
            [
                (
                    "unsuitable-field",
                    "The column 'meta' of the lines 'Line' (json) has no widget in a lines editor.",
                )
            ],
        ),
    ],
    ids=["no-fields", "required", "duplicate", "inverse", "computed", "many", "json"],
)
def test_the_columns_of_a_lines_editor_are_fields_of_a_new_line(
    editor: str, expected: list[tuple[str, str]]
) -> None:
    assert problems(definition_text(editor)) == expected


def test_the_operation_of_the_form_writes_the_lines_of_the_editor() -> None:
    text = definition_text().replace(
        "  create_order: { kind: create, entity: Order, lines: [lines] }",
        "  create_order: { kind: create, entity: Order }",
    )
    assert problems(text) == [
        (
            "unsuitable-operation",
            "The operation 'create_order' does not write the lines 'lines', so the form cannot "
            "send them.",
        )
    ]


def test_only_the_widget_lines_takes_fields() -> None:
    text = definition_text().replace("number: {}", "number: { fields: [amount] }")
    assert problems(text) == [("unsuitable-field", "'fields' is only for the widget 'lines'.")]


def test_a_one_to_many_relation_without_a_widget_gets_the_hint_of_the_lines_editor() -> None:
    definition = load_definition_text(definition_text("{}"), "app.yaml")
    [problem] = validate_definition(definition)
    assert problem.code == "missing-widget"
    assert problem.hint == "Set 'widget: lines' with 'fields', or 'widget: custom'."


def test_the_plan_of_a_lines_editor_has_a_column_for_each_field() -> None:
    definition = load_definition_text(definition_text(), "app.yaml")
    plan = FormContext(definition).plan("new_order")
    [editor] = plan.lines
    assert editor.key == "lines"
    assert editor.initial == "[]"
    assert editor.lines is not None
    assert editor.lines.row_type == "LinesRow"
    assert [c.key for c in editor.lines.columns] == ["amount", "productId"]
    assert [c.element_id for c in editor.lines.columns] == [
        "entities.Line.fields.amount",
        "entities.Line.relations.product",
    ]
    assert editor.lines.columns[0].to_input == "line.amount"
    assert plan.call == "createOrder(input as OrderInput, lines)"
    assert 'import { createOrder, type CreateOrderLines } from "@/features/create-order";' in (
        plan.imports
    )
    assert [(t.key, t.code) for t in plan.totals] == [
        ("sumLinesAmount", 'linesTotal("sum", linesRecords(values.lines), "amount")')
    ]
    assert [(p.label, p.editor) for p in plan.previews] == [("Total", "lines")]


def test_a_form_without_a_lines_editor_sends_no_lines() -> None:
    definition = load_definition_text(
        definition_text().replace("        lines: " + EDITOR + "\n", ""), "app.yaml"
    )
    plan = FormContext(definition).plan("new_order")
    assert plan.call == "createOrder(input as OrderInput)"
    assert 'import { createOrder } from "@/features/create-order";' in plan.imports


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_an_operation_with_lines_is_a_feature_slice(binding: Binding) -> None:
    files = files_of(load_definition(FIXTURE), binding)
    slice_index = files["src/features/create-invoice/index.ts"]
    assert 'export { createInvoice, type CreateInvoiceLines } from "./api/create-invoice-api";' in (
        slice_index
    )
    assert "createInvoice" not in files["src/entities/invoice/index.ts"]
    assert "invoiceLinesItemSchema," in files["src/entities/invoice-line/index.ts"]
    assert (
        'export type InvoiceLinesItem = Omit<InvoiceLineInput, "invoiceId"> & { id?: string };'
        in files["src/entities/invoice-line/model/types.ts"]
    )
    lines = files["src/shared/api/lines.ts"]
    assert "export async function writeLines<" in lines
    assert "await lines.remove(line.id);" in lines


def test_the_nextjs_action_writes_the_record_and_its_lines_in_one_transaction() -> None:
    files = files_of(load_definition(FIXTURE), nextjs.BINDING)
    action = files["src/features/create-invoice/api/create-invoice-action.ts"]
    assert '"use server";' in action
    assert "lines: z.array(invoiceLinesItemSchema).optional()," in action
    assert "return inTransaction(async () => {" in action
    assert (
        'await writeLines(invoiceLineRepository, "InvoiceLine", "invoiceId", record.id, '
        'items.lines, "lines");'
    ) in action
    assert "export async function inTransaction<T>(" in files["src/shared/db/client.ts"]


def test_the_react_function_writes_the_lines_in_the_mock_data_or_sends_them() -> None:
    files = files_of(load_definition(FIXTURE), react.BINDING)
    mock = files["src/features/create-invoice/api/create-invoice-api.ts"]
    assert "return inTransaction(async () => {" in mock
    assert "export async function inTransaction<R>(" in files["src/shared/api/mock-store.ts"]
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "  name: totals-check\n", "  name: totals-check\n  x-react-data: api\n"
    )
    api_files = files_of(load_definition_text(text, str(FIXTURE)), react.BINDING)
    api = api_files["src/features/create-invoice/api/create-invoice-api.ts"]
    assert "lines: lines.lines?.map((item) => invoiceLineApi.json(item))," in api
    assert "const record = await invoiceApi.create(input, more);" in api
    assert "src/shared/api/lines.ts" not in api_files


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_a_form_edits_the_lines_and_shows_their_totals_before_the_save(binding: Binding) -> None:
    files = files_of(load_definition(FIXTURE), binding)
    new = files["src/features/new-invoice-form/ui/new-invoice-form.tsx"]
    assert "function newLinesRow(): LinesRow {" in new
    assert "const parsed = invoiceLinesItemSchema.safeParse(linesItem(line));" in new
    assert "schemaErrors(parsed.error, errors, `lines.${index}`);" in new
    assert 'if (values.lines.length === 0) errors.lines ??= "Add a line.";' in new
    assert "await createInvoice(input as InvoiceInput, lines);" in new
    assert 'const found = submitErrors(error, ["lines"]);' in new
    assert 'sumLinesAmount: linesTotal("sum", linesRecords(values.lines), "amount"),' in new
    assert '<FieldLegend variant="label">Lines</FieldLegend>' in new
    assert "{/* @trace entities.Invoice.fields.subtotal */}" in new
    edit = files["src/features/edit-invoice-form/ui/edit-invoice-form.tsx"]
    assert "listLinesOfInvoice(id, { pageSize: 1000 })," in edit
    assert "lines: lines?.lines.map(linesRow) ?? []," in edit
    assert "return <EditInvoiceFormBody {...props} lines={lines.data} />;" in edit
    assert "export function linesTotal(" in files["src/shared/lib/form.ts"]


def test_the_fastapi_tests_of_long_operation_names_fit_in_the_line_length() -> None:
    text = (
        FIXTURE.read_text(encoding="utf-8")
        .replace("create_invoice", "create_invoice_with_all_of_its_lines")
        .replace("update_invoice", "update_invoice_with_all_of_its_lines")
    )
    files = files_of(load_definition_text(text, str(FIXTURE)), fastapi.BINDING)
    tests = {path: content for path, content in files.items() if path.startswith("tests/")}
    update = tests["tests/features/invoices/test_update_invoice_with_all_of_its_lines_lines.py"]
    assert (
        "    response = await client.patch(\n"
        '        f"/invoices/{record.id}/update-invoice-with-all-of-its-lines",\n'
        '        json={"lines": items},\n'
        "    )\n"
    ) in update
    # The docstrings can be longer: the formatter keeps them.
    long_lines = [
        (path, line)
        for path, content in tests.items()
        for line in content.splitlines()
        if len(line) > 100 and not line.startswith('"""')
    ]
    assert long_lines == []
