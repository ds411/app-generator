"""The currency of each record (`currency_field`): the checks, the views, the forms, and the
stat widgets of the front ends."""

from pathlib import Path
from textwrap import dedent, indent

import pytest

from appgen.bindings import nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.ui.dashboards import currency_path, single_value
from appgen.gen import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "invoices.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: billing, title: Billing }
    entities:
      Customer:
        crud: { views: [table], forms: [create] }
        display_field: name
        fields:
          name: { type: string, required: true }
          currency: { type: enum, values: [usd, eur], default: usd }
          code: { type: string, max_length: 3 }
      Invoice:
        crud: { views: [table, detail], forms: [create, update] }
        display_field: title
        fields:
          title: { type: string, required: true }
          currency: { type: string, max_length: 3 }
          total: { type: decimal, format: currency, currency_field: customer.currency }
          fee: { type: decimal, format: currency, currency_field: currency, currency: EUR }
        relations:
          customer: { kind: many_to_one, target: Customer, required: true }
    """
)

DASHBOARD = dedent(
    """\
    ui:
      dashboards:
        overview:
          widgets:
            sales: {widget}
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_number_field_takes_the_currency_of_its_record() -> None:
    assert codes(BASE) == []
    assert validate_definition(load_definition(FIXTURE)) == []


def test_only_a_number_field_takes_a_currency_field() -> None:
    text = BASE.replace(
        "title: { type: string, required: true }\n      currency:",
        "title: { type: string, required: true, currency_field: currency }\n      currency:",
    )
    assert codes(text) == [("invalid-option", "entities.Invoice.fields.title")]


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("customer.money", "unknown-reference"),
        ("customer.name", None),
        ("customer.code", None),
        ("customer", "unsuitable-field"),
        ("title.currency", "unknown-reference"),
    ],
)
def test_the_currency_field_is_a_string_or_an_enum_field(path: str, code: str | None) -> None:
    text = BASE.replace("currency_field: customer.currency }", f"currency_field: {path} }}")
    found = codes(text)
    assert found == ([] if code is None else [(code, "entities.Invoice.fields.total")])


def test_the_values_of_an_enum_currency_field_are_currency_codes() -> None:
    text = BASE.replace("values: [usd, eur]", "values: [usd, euro]")
    assert codes(text) == [("invalid-value", "entities.Invoice.fields.total")]


def test_a_param_takes_no_currency_field() -> None:
    text = BASE + dedent(
        """\
        operations:
          refund:
            kind: custom
            entity: Invoice
            params:
              amount: { type: decimal, currency_field: currency }
        """
    )
    assert codes(text) == [("invalid-option", "operations.refund.params.amount")]


def test_a_filter_gives_one_value_of_a_path() -> None:
    assert single_value({"customer.currency": "eur"}, "customer.currency") == "eur"
    assert single_value({"customer.currency": {"eq": "eur"}}, "customer.currency") == "eur"
    assert single_value({"customer.currency": {"in": ["eur"]}}, "customer.currency") == "eur"
    assert single_value({"customer.currency": {"in": ["eur", "usd"]}}, "customer.currency") is None
    assert single_value({"customer.currency": {"ne": "eur"}}, "customer.currency") is None
    assert single_value({}, "customer.currency") is None
    assert currency_path("total", "customer.currency") == "customer.currency"
    assert currency_path("invoice.total", "customer.currency") == "invoice.customer.currency"


@pytest.mark.parametrize(
    ("widget", "valid"),
    [
        ("{ kind: stat, entity: Invoice, aggregate: sum, field: total }", False),
        (
            "{ kind: stat, entity: Invoice, aggregate: sum, field: total, "
            "filter: { customer.currency: eur } }",
            True,
        ),
        (
            "{ kind: stat, entity: Invoice, aggregate: avg, field: total, "
            "filter: { customer.currency: { in: [eur, usd] } } }",
            False,
        ),
        ("{ kind: stat, entity: Invoice }", True),
        (
            "{ kind: chart, chart: bar, entity: Invoice, group_by: customer.currency, "
            "aggregate: sum, field: total }",
            True,
        ),
        (
            "{ kind: chart, chart: bar, entity: Invoice, group_by: customer, "
            "aggregate: sum, field: total }",
            False,
        ),
    ],
)
def test_an_aggregate_of_amounts_needs_one_currency(widget: str, valid: bool) -> None:
    text = BASE + DASHBOARD.replace("{widget}", widget)
    expected = [] if valid else [("unsuitable-field", "ui.dashboards.overview.widgets.sales")]
    assert codes(text) == expected


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_the_views_show_each_amount_in_the_currency_of_its_record(binding: Binding) -> None:
    files = files_of(BASE, binding)
    table = files["src/widgets/invoice-table/ui/invoice-table-view.tsx"]
    assert (
        '<FormattedValue value={row.total} format="currency" '
        'currency={lookups.customer.get(row.customerId ?? "")?.currency} />'
    ) in table
    assert 'currency={row.currency ?? "EUR"} />' in table
    detail = files["src/widgets/invoice-detail/ui/invoice-detail-view.tsx"]
    assert 'currency={lookups.customer.get(record.customerId ?? "")?.currency}' in detail
    lib = files["src/shared/lib/format.ts"]
    assert "export function currencyCode(currency: string | null | undefined): string {" in lib


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_the_forms_show_each_amount_in_the_currency_of_its_record(binding: Binding) -> None:
    files = files_of(BASE, binding)
    new = files["src/features/new-invoice-form/ui/new-invoice-form.tsx"]
    assert 'currency={related.customer.get(values.customerId ?? "")?.currency}' in new
    assert 'currency={values.currency ?? "EUR"}' in new
    edit = files["src/features/edit-invoice-form/ui/edit-invoice-form.tsx"]
    assert 'currency={values.currency ?? "EUR"}' in edit


def test_an_edit_form_without_the_currency_field_reads_the_record() -> None:
    text = BASE.replace(
        "crud: { views: [table, detail], forms: [create, update] }",
        "crud: { views: [table, detail], forms: [] }",
    ) + dedent(
        """\
        ui:
          forms:
            edit_fee:
              entity: Invoice
              operation: update_invoice
              fields: { fee: {}, total: {} }
        """
    )
    files = files_of(text, nextjs.BINDING)
    form = files["src/features/edit-fee-form/ui/edit-fee-form.tsx"]
    assert 'currency={record?.currency ?? "EUR"}' in form
    # Without the relation field, the form does not know the customer.
    total = next(line for line in form.splitlines() if 'id="edit-fee-total"' in line)
    assert "currency=" not in total


def test_a_stat_shows_the_currency_of_its_filter() -> None:
    widget = (
        "{ kind: stat, entity: Invoice, aggregate: sum, field: total, "
        "filter: { customer.currency: eur } }"
    )
    files = files_of(BASE + DASHBOARD.replace("{widget}", widget), react.BINDING)
    dashboard = files["src/widgets/overview/ui/overview-dashboard.tsx"]
    assert 'value={formatValue(sales(data), "currency", "EUR")}' in dashboard


LINES = indent(
    dedent(
        """\
        Line:
          crud: { views: [table] }
          display_field: text
          fields:
            text: { type: string, required: true }
            amount: { type: decimal, format: currency, currency_field: invoice.customer.currency }
          relations:
            invoice: { kind: many_to_one, target: Invoice, required: true }
        """
    ),
    "  ",
)


@pytest.mark.parametrize("api", [False, True], ids=["mock", "api"])
def test_a_view_reads_the_records_of_the_currency(api: bool) -> None:
    text = BASE + LINES
    if api:
        text = text.replace("title: Billing }", "title: Billing, x-react-data: api }")
    files = files_of(text, react.BINDING)
    table = files["src/widgets/line-table/ui/line-table-view.tsx"]
    lookups = 'lookups.customer.get(lookups.invoice.get(row.invoiceId ?? "")?.customerId ?? "")'
    assert f"currency={{{lookups}?.currency}}" in table
    if api:
        # The related records of the page: the invoices, then their customers.
        assert '{ from: "invoice", key: "customerId" }' in table
    else:
        assert "customer: byId(customerList.items), invoice: byId(invoiceList.items)" in table
