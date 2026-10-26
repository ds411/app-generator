"""The sequence numbers of the fields: the DSL, the checks, and the code of the apps (ADR 0037)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.bindings.shared.mock_data import mock_data
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.dsl.schema import json_schema
from appgen.gen import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "invoices.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: billing, title: Billing }
    entities:
      Invoice:
        crud: { views: [table], forms: [create, update] }
        display_field: number
        fields:
          number:
            type: string
            unique: true
            sequence: { start: 1001, prefix: INV-, width: 4 }
          position: { type: integer, sequence: {} }
          title: { type: string, required: true }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_sequence_gives_the_text_of_a_number() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    invoice = definition.entities["Invoice"]
    number = invoice.fields["number"].sequence
    position = invoice.fields["position"].sequence
    assert number is not None and position is not None
    assert (number.start, number.prefix, number.width) == (1001, "INV-", 4)
    assert number.text(42) == "INV-0042"
    assert number.text(12345) == "INV-12345"
    assert (position.start, position.text(7)) == (1, "7")
    assert list(invoice.sequence_fields) == ["number", "position"]
    assert number.id == "entities.Invoice.fields.number.sequence"
    assert codes(BASE) == []


def test_the_invoices_fixture_is_valid() -> None:
    definition = load_definition(FIXTURE)
    assert validate_definition(definition) == []


@pytest.mark.parametrize(
    "sequence",
    ["{ start: 0 }", "{ prefix: 'INV 1' }", "{ width: 16 }", "{ start: 1000000000000001 }"],
)
def test_a_sequence_with_a_value_out_of_range_is_an_error(sequence: str) -> None:
    text = BASE.replace("{ start: 1001, prefix: INV-, width: 4 }", sequence)
    with pytest.raises(DefinitionError) as caught:
        load_definition_text(text, "app.yaml")
    assert [d.code for d in caught.value.diagnostics] == ["invalid-value"]


def test_a_sequence_is_for_a_string_or_an_integer_field() -> None:
    text = BASE.replace("type: integer, sequence: {}", "type: date, sequence: {}")
    assert codes(text) == [("invalid-option", "entities.Invoice.fields.position")]


def test_the_prefix_and_the_width_are_only_for_a_string() -> None:
    text = BASE.replace("sequence: {}", "sequence: { prefix: N-, width: 3 }")
    assert codes(text) == [
        ("invalid-option", "entities.Invoice.fields.position.sequence"),
        ("invalid-option", "entities.Invoice.fields.position.sequence"),
    ]


@pytest.mark.parametrize(
    "option",
    [
        "required: true",
        "default: 5",
        "min: 1",
        "max: 9",
        "computed: position * 2",
    ],
)
def test_a_sequence_field_takes_no_value_from_elsewhere(option: str) -> None:
    text = BASE.replace("sequence: {}", f"sequence: {{}}, {option}")
    assert ("invalid-option", "entities.Invoice.fields.position") in codes(text)


def test_a_param_takes_no_sequence() -> None:
    text = BASE + dedent(
        """\
        operations:
          renumber:
            kind: custom
            entity: Invoice
            params:
              next: { type: integer, sequence: {} }
        """
    )
    assert codes(text) == [("invalid-option", "operations.renumber.params.next")]


def test_a_seed_record_gives_no_value_of_a_sequence_field() -> None:
    text = BASE + dedent(
        """\
        seed:
          Invoice:
            records:
              first: { title: First, number: INV-0001 }
        """
    )
    definition = load_definition_text(text, "app.yaml")
    diagnostics = validate_definition(definition)
    assert [(d.code, d.element_id) for d in diagnostics] == [
        ("unsuitable-field", "seed.Invoice.records.first")
    ]
    assert (
        diagnostics[0].hint == "Remove the value. The seed records get the numbers in their order."
    )


def test_a_form_cannot_change_a_sequence_field() -> None:
    text = BASE.replace("forms: [create, update]", "forms: []") + dedent(
        """\
        ui:
          forms:
            invoice_form:
              entity: Invoice
              operation: create_invoice
              fields: { title: {}, number: {} }
        """
    )
    assert codes(text) == [("unsuitable-field", "ui.forms.invoice_form.fields.number")]


def test_the_default_forms_leave_out_a_sequence_field() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.ui is not None
    for name in ("new_invoice", "edit_invoice"):
        assert list(definition.ui.forms[name].fields) == ["title"]


def test_the_schema_has_the_sequence_of_a_field() -> None:
    schema = json_schema()
    sequence = schema["$defs"]["Sequence"]
    assert set(sequence["properties"]) == {"start", "prefix", "width"}
    assert sequence["additionalProperties"] is False


def test_the_mock_records_have_the_numbers_in_order() -> None:
    definition = load_definition(FIXTURE)
    records = mock_data(definition)
    invoices = records["Invoice"]
    assert [record["number"] for record in invoices] == [f"INV-{n}" for n in range(1001, 1007)]
    lines = records["Line"]
    assert [record["position"] for record in lines] == list(range(1, len(lines) + 1))


def test_the_nextjs_app_takes_the_numbers_from_database_sequences() -> None:
    files = files_of(BASE, nextjs.BINDING)
    schema = files["src/shared/db/schema/invoice.ts"]
    assert 'pgSequence("invoice_number_seq", { startWith: 1001 });' in schema
    assert (
        "default(sql`('INV-' || to_char(nextval('invoice_number_seq'), 'FM9999999999999990000'))`)"
        in schema
    )
    position = 'position: bigint("position", { mode: "number" }).notNull()'
    assert position + ".default(sql`nextval('invoice_position_seq')`)" in schema
    types = files["src/entities/invoice/model/types.ts"]
    input_type = types.split("export type InvoiceInput = {", 1)[1].split("};", 1)[0]
    assert "number" not in input_type and "position" not in input_type
    assert "  number: string; // @trace entities.Invoice.fields.number\n" in types


def test_the_react_mock_store_gives_the_next_numbers() -> None:
    files = files_of(BASE, react.BINDING)
    api = files["src/entities/invoice/api/invoice-api.ts"]
    assert '{ key: "number", start: 1001, prefix: "INV-", width: 4 },' in api
    assert '{ key: "position", start: 1 },' in api
    store = files["src/shared/api/mock-store.ts"]
    assert "withSequences(" in store and "...this.nextNumbers()" in store


def test_the_fastapi_app_takes_the_numbers_from_the_database() -> None:
    files = files_of(BASE, fastapi.BINDING)
    models = files["app/features/invoices/models.py"]
    assert (
        'NUMBER_SEQUENCE = Sequence("invoices_number_seq", start=1001, metadata=Base.metadata)'
        in models
    )
    assert (
        'default=NextNumber(NUMBER_SEQUENCE, "invoices", "number", prefix="INV-", width=4)'
        in models
    )
    assert '"eager_defaults": True' in models
    schemas = files["app/features/invoices/schemas.py"]
    create = schemas.split("class InvoiceCreate(", 1)[1].split("\n\n\n", 1)[0]
    assert "number" not in create and "position" not in create
    migration = files["migrations/versions/0001_schema.py"]
    assert (
        'op.execute(sa.schema.CreateSequence(sa.Sequence("invoices_number_seq", start=1001)))'
        in migration
    )
    assert 'op.execute(sa.schema.DropSequence(sa.Sequence("invoices_position_seq")))' in migration
    db = files["app/core/db.py"]
    assert "class NextNumber(ColumnElement[Any]):" in db
    tests = files["tests/features/invoices/test_create_invoice.py"]
    assert "async def test_create_invoice_gives_the_next_number(" in tests


def test_a_line_of_a_record_gets_the_next_number() -> None:
    files = files_of(
        FIXTURE.read_text().replace(
            "seed:\n",
            "operations:\n"
            "  create_invoice_lines: { kind: create, entity: Invoice, lines: [lines] }\n\n"
            "seed:\n",
            1,
        ),
        fastapi.BINDING,
    )
    schemas = files["app/features/lines/schemas.py"]
    item = schemas.split("class InvoiceLinesItem(", 1)[1].split("\n\n\n", 1)[0]
    assert "text: str" in item and "position" not in item


def test_an_app_without_sequences_has_no_sequence_code() -> None:
    text = "".join(line for line in BASE.splitlines(keepends=True) if "sequence: {" not in line)
    assert "pgSequence" not in "".join(files_of(text, nextjs.BINDING).values())
    assert (
        "withSequences("
        not in files_of(text, react.BINDING)["src/entities/invoice/api/invoice-api.ts"]
    )
    fastapi_files = files_of(text, fastapi.BINDING)
    assert "NextNumber" not in "".join(fastapi_files.values())
    assert "CreateSequence" not in fastapi_files["migrations/versions/0001_schema.py"]


def test_the_three_bindings_cover_the_sequences() -> None:
    for binding in (fastapi.BINDING, nextjs.BINDING, react.BINDING):
        assert "sequence" in binding.covers
