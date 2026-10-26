"""The lines of a record in create and update operations (ADR 0035): the DSL, the checks,
and the FastAPI app."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.schema import json_schema
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "totals.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Order:
        crud: true
        fields:
          number: { type: string, required: true }
        relations:
          lines: { kind: one_to_many, target: Line, inverse: order }
          notes: { kind: one_to_many, target: Note, inverse: order }
          customer: { kind: many_to_one, target: Customer }
      Line:
        crud: true
        fields:
          amount: { type: decimal, scale: 2, required: true }
        relations:
          order: { kind: many_to_one, target: Order, required: true, inverse: lines }
          product: { kind: many_to_one, target: Product }
      Note:
        fields:
          text: { type: text }
        relations:
          order: { kind: many_to_one, target: Order, required: true, inverse: notes }
      Customer:
        fields:
          name: { type: string }
      Product:
        fields:
          name: { type: string }
    operations:
    {operations}
    """
)


def definition_text(operations: str) -> str:
    """Return the base definition with operations, one on each line."""
    return BASE.replace("{operations}", operations)


def errors(operations: str) -> list[tuple[str, str]]:
    definition = load_definition_text(definition_text(operations), "app.yaml")
    return [(d.code, d.message) for d in validate_definition(definition)]


def files_of(operations: str) -> dict[str, str]:
    definition = load_definition_text(definition_text(operations), "app.yaml")
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


CREATE = "  create_order: { kind: create, entity: Order, lines: [lines, notes] }"
UPDATE = "  update_order: { kind: update, entity: Order, lines: [lines] }"


def test_a_create_and_an_update_operation_write_lines() -> None:
    assert errors(f"{CREATE}\n{UPDATE}") == []


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (
            "  list_orders: { kind: list, entity: Order, lines: [lines] }",
            ("invalid-option", "'lines' is only for a create or an update operation."),
        ),
        (
            "  create_order: { kind: create, entity: Order, lines: [linez] }",
            ("unknown-reference", "The entity 'Order' has no relation 'linez'."),
        ),
        (
            "  create_order: { kind: create, entity: Order, lines: [customer] }",
            (
                "unsuitable-field",
                "The lines 'customer' need a one_to_many relation, but 'Order.customer' is "
                "many_to_one.",
            ),
        ),
        (
            "  create_order: { kind: create, entity: Order, lines: [lines, lines] }",
            ("duplicate-name", "The names in 'lines' must be unique."),
        ),
    ],
    ids=["list", "unknown", "many-to-one", "duplicate"],
)
def test_the_lines_are_one_to_many_relations_of_a_create_or_an_update(
    operation: str, expected: tuple[str, str]
) -> None:
    assert errors(operation) == [expected]


def test_the_lines_have_no_file_fields() -> None:
    text = definition_text(CREATE).replace(
        "text: { type: text }", "text: { type: text }\n      scan: { type: file }"
    )
    text += "storage: { kind: local }\n"
    definition = load_definition_text(text, "app.yaml")
    assert [(d.code, d.message) for d in validate_definition(definition)] == [
        (
            "unsuitable-field",
            "The lines 'notes' are records of 'Note', which has the file field 'scan'. The "
            "lines of an operation cannot have files.",
        )
    ]


def test_the_schema_has_the_lines_of_an_operation() -> None:
    operation = json_schema()["$defs"]["Operation"]["properties"]
    assert operation["lines"]["type"] == "array"


def test_the_fastapi_operation_takes_the_lines_in_its_body() -> None:
    files = files_of(f"{CREATE}\n{UPDATE}")
    create = files["app/features/orders/create_order.py"]
    assert "from app.core.db import SessionDep, commit, flush" in create
    assert "from app.features.lines.schemas import OrderLinesItem" in create
    assert "from app.features.notes.schemas import OrderNotesItem" in create
    assert "class CreateOrderInput(OrderCreate):" in create
    assert (
        "    lines: list[OrderLinesItem] = Field(\n"
        "        default_factory=list[OrderLinesItem],\n"
        "        exclude=True,\n"
        '        description="The new records of `lines`.",\n'
        "    )\n"
    ) in create
    assert (
        "    record = await repository.add(session, data)\n"
        "    # The lines refer to the new record.\n"
        "    await flush(session)\n"
        "    # @trace entities.Order.relations.lines\n"
        "    await repository.write_lines(session, record, data.lines)\n"
        "    # @trace entities.Order.relations.notes\n"
        "    await repository.write_notes(session, record, data.notes)\n"
        "    await commit(session)\n"
        "    record = await repository.get(session, record.id)\n"
    ) in create
    update = files["app/features/orders/update_order.py"]
    assert "class UpdateOrderInput(OrderUpdate):" in update
    assert "    lines: list[OrderLinesItem] | None = Field(\n" in update
    assert (
        "    if data.lines is not None:\n"
        "        await repository.write_lines(session, record, data.lines)\n"
        "    record = await repository.update(session, record, data)\n"
    ) in update


def test_the_fastapi_repository_writes_the_lines_in_the_transaction_of_the_record() -> None:
    files = files_of(f"{CREATE}\n{UPDATE}")
    orders = files["app/features/orders/repository.py"]
    assert "from app.features.lines import repository as line_repository" in orders
    assert "from app.features.lines.schemas import LineCreate, LineUpdate, OrderLinesItem" in orders
    assert "statement = select(Line).where(Line.order_id == record.id)" in orders
    assert "await line_repository.remove(session, line)" in orders
    assert "await line_repository.add(session, data)" in orders
    assert "await line_repository.change(session, line, changes)" in orders
    assert 'raise error.at("body", "lines", index) from error' in orders
    assert "async def write_notes(" in orders
    lines = files["app/features/lines/repository.py"]
    assert "async def change(session: AsyncSession, record: Line, data: LineUpdate) -> None:" in (
        lines
    )
    assert "    await change(session, record, data)\n    await commit(session)\n" in lines
    assert "    await remove(session, record)\n    await commit(session)\n" in lines
    schemas = files["app/features/lines/schemas.py"]
    item = schemas.split("class OrderLinesItem(InputModel):")[1].split("\nclass ")[0]
    assert "    id: UUID | None = Field(" in item
    assert "    amount: Decimal\n" in item
    assert "    product_id: UUID | None = None\n" in item
    assert "order_id" not in item
    errors_module = files["app/core/errors.py"]
    assert "def at(self, *loc: str | int) -> ProblemError:" in errors_module
    assert "error.status, error.detail, error.errors" in errors_module


def test_an_app_without_lines_keeps_its_repositories_and_errors() -> None:
    files = files_of("  create_order: { kind: create, entity: Order }")
    assert "async def change(" not in files["app/features/lines/repository.py"]
    assert "async def remove(" not in files["app/features/lines/repository.py"]
    assert "def at(" not in files["app/core/errors.py"]
    assert "class OrderLinesItem" not in files["app/features/lines/schemas.py"]


def test_the_fastapi_app_tests_the_lines_of_each_operation() -> None:
    definition = load_definition(FIXTURE)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    create = files["tests/features/invoices/test_create_invoice_lines.py"]
    assert "async def test_create_invoice_stores_the_lines(" in create
    assert "async def test_create_invoice_stores_nothing_for_an_error_in_a_line_of_lines(" in (
        create
    )
    assert "async def test_create_invoice_checks_the_line_status_of_the_lines(" in create
    update = files["tests/features/invoices/test_update_invoice_lines.py"]
    assert "async def test_update_invoice_replaces_the_lines(" in update
    assert "async def test_update_invoice_keeps_the_lines_without_lines(" in update
    assert "async def test_update_invoice_changes_nothing_for_an_error_in_a_line_of_lines(" in (
        update
    )
    assert '"CreateInvoiceInput",' in files["tests/test_openapi.py"]
    assert '"InvoiceLinesItem",' in files["tests/test_openapi.py"]
