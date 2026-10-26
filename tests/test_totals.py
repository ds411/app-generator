"""The totals of the relations in the computed fields (ADR 0034): the DSL, the checks, the apps."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.schema import json_schema
from appgen.gen import Binding
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "totals.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Order:
        crud: { views: [table, detail] }
        fields:
          number: { type: string, required: true }
          fee: { type: decimal, scale: 2 }
          {field}
        relations:
          lines: { kind: one_to_many, target: Line, inverse: order }
          customer: { kind: many_to_one, target: Customer }
          tags: { kind: many_to_many, target: Tag }
      Line:
        crud: true
        fields:
          label: { type: string }
          amount: { type: decimal, scale: 2 }
          double: { type: decimal, computed: amount * 2 }
          kind: { type: enum, values: [debit, credit] }
          posted_on: { type: date }
        relations:
          order: { kind: many_to_one, target: Order, required: true, inverse: lines }
      Customer:
        fields:
          name: { type: string }
      Tag:
        crud: true
        fields:
          name: { type: string }
          weight: { type: integer }
    """
)


def order_field(text: str) -> str:
    """Return the base definition with one more field of Order."""
    return BASE.replace("{field}", text)


def diagnostics(text: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding = fastapi.BINDING) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_computed_field_counts_and_adds_the_records_of_a_relation() -> None:
    for computed in (
        "count(lines)",
        "sum(lines.amount) + fee",
        "avg(lines.amount)",
        "min(lines.amount) * 2",
        "max(lines.amount)",
        "count(tags)",
        "sum(tags.weight)",
        "sum(lines.amount) - sum(lines.amount)",
    ):
        text = order_field(f"total: {{ type: decimal, computed: '{computed}' }}")
        assert diagnostics(text) == [], computed


def test_a_total_needs_a_relation_to_many_records_and_a_stored_number_field() -> None:
    def errors(computed: str) -> list[tuple[str, str]]:
        text = order_field(f"total: {{ type: decimal, computed: '{computed}' }}")
        return [(code, message) for code, _, message in diagnostics(text)]

    assert errors("count(customer)") == [
        (
            "unsuitable-field",
            "The total 'count(customer)' needs a one_to_many or a many_to_many relation, but "
            "'Order.customer' is many_to_one.",
        )
    ]
    assert errors("sum(lines.label)") == [
        (
            "unsuitable-field",
            "The total 'sum(lines.label)' needs an 'integer' or a 'decimal' field, but "
            "'Line.label' is 'string'.",
        )
    ]
    assert errors("sum(lines.double)") == [
        (
            "unsuitable-field",
            "The total 'sum(lines.double)' adds the computed field 'Line.double'. A total adds "
            "only stored fields.",
        )
    ]
    assert errors("count(linez)") == [
        ("unknown-reference", "The entity 'Order' has no relation 'linez'.")
    ]
    assert errors("max(lines.amout)") == [
        ("unknown-reference", "The entity 'Line' has no field 'amout'.")
    ]
    assert errors("hours(count(lines), fee)") == [
        (
            "invalid-value",
            "The arguments of 'hours' must be field paths of dates or date-times.",
        ),
        ("unsuitable-field", "The path 'fee' must give a date or a date-time."),
    ]


def test_a_filter_selects_the_related_records_of_the_totals() -> None:
    text = order_field(
        "debits: { type: decimal, computed: sum(lines.amount), filter: { kind: debit } }"
    )
    assert diagnostics(text) == []
    text = order_field(
        "debits:\n"
        "          type: decimal\n"
        "          computed: sum(lines.amount)\n"
        "          filter: { kind: debt, posted_on: { lt: $today }, order: x, label: { has: a } }"
    )
    assert [(code, message) for code, _, message in diagnostics(text)] == [
        (
            "invalid-value",
            "The filter of the totals cannot use $today or $now ('posted_on').",
        ),
        (
            "unknown-reference",
            "The filter of the totals names 'order', which is not a stored field of the "
            "entity 'Line'.",
        ),
        ("unknown-reference", "The enum value 'debt' does not exist."),
        ("unknown-reference", "The filter operator 'has' does not exist."),
    ]


def test_a_filter_is_only_for_a_computed_field_with_totals() -> None:
    for field in (
        "x: { type: decimal, filter: { kind: debit } }",
        "x: { type: decimal, computed: fee * 2, filter: { kind: debit } }",
    ):
        assert [(c, m) for c, _, m in diagnostics(order_field(field))] == [
            ("invalid-option", "'filter' is only for a computed field with totals.")
        ]


def test_the_schema_has_the_filter_of_a_computed_field() -> None:
    field = json_schema()["$defs"]["Field"]["properties"]
    assert "filter" in field
    assert "computed" in field


def test_the_fastapi_model_reads_each_total_in_a_subquery() -> None:
    files = files_of(
        order_field(
            "total: { type: decimal, scale: 2, computed: sum(lines.amount) + fee }\n"
            "      subtotal: { type: decimal, scale: 2, computed: sum(lines.amount) }\n"
            "      debits:\n"
            "        type: decimal\n"
            "        computed: sum(lines.amount)\n"
            "        filter: { kind: debit }\n"
            "      tag_weight: { type: integer, computed: sum(tags.weight) }"
        )
    )
    models = files["app/models.py"]
    assert "from sqlalchemy.orm import column_property, configure_mappers" in models
    assert "from app.core import totals" in models
    assert "from app.features.lines.enums import LineKind" in models
    assert "from app.features.orders.models import Order, orders_tags" in models
    # Two fields share a total without a filter: one column property.
    assert models.count("Order.sum_lines_amount = column_property(") == 1
    assert (
        "# @trace entities.Order.fields.total\n"
        "# @trace entities.Order.fields.subtotal\n"
        "Order.sum_lines_amount = column_property(\n"
        '    totals.total("sum", Line, Line.amount, Line.order_id == Order.id),\n'
        ")"
    ) in models
    assert (
        "# @trace entities.Order.fields.debits\n"
        "Order.debits_sum_lines_amount = column_property(\n"
        '    totals.total("sum", Line, Line.amount, Line.order_id == Order.id, '
        "Line.kind == LineKind.DEBIT),\n"
        ")"
    ) in models
    assert (
        "Order.sum_tags_weight = column_property(\n"
        "    totals.total(\n"
        '        "sum",\n'
        "        Tag,\n"
        "        Tag.weight,\n"
        "        orders_tags.c.order_id == Order.id,\n"
        "        orders_tags.c.tag_id == Tag.id,\n"
        "        via=orders_tags,\n"
        "    ),\n"
        ")"
    ) in models
    model = files["app/features/orders/models.py"]
    assert "    if TYPE_CHECKING:\n" in model
    assert "        sum_lines_amount: Mapped[Decimal]\n" in model
    assert "        sum_tags_weight: Mapped[int]\n" in model
    assert "        v1 = compute.num(self.sum_lines_amount)\n" in model
    assert "app/core/totals.py" in files
    assert "def total(" in files["app/core/totals.py"]


def test_the_fastapi_list_sorts_and_filters_by_a_total() -> None:
    files = files_of(
        order_field(
            "total: { type: decimal, scale: 2, computed: sum(lines.amount) - -fee * 2 }\n"
            "      share: { type: decimal, scale: 2, computed: sum(lines.amount) / 2 }"
        )
    )
    listing = files["app/features/orders/list_orders.py"]
    assert "from app.models import Customer, Order" in listing
    assert '"total": Order.sum_lines_amount - -Order.fee * Decimal("2"),' in listing
    assert '"share"' not in listing
    assert "total_min: Decimal | None = Field(" in listing
    assert (
        "    if query.total_max is not None:\n"
        "        statement = statement.where(\n"
        '            Order.sum_lines_amount - -Order.fee * Decimal("2") <= query.total_max,\n'
        "        )\n"
    ) in listing


def test_the_fastapi_app_tests_each_function_of_the_totals() -> None:
    definition = load_definition(FIXTURE)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    invoices = files["tests/features/invoices/test_totals.py"]
    assert 'LINES: list[dict[str, Any]] = [\n    {"amount": Decimal("13.00")},' in invoices
    assert '("line_count", [0, 1, 3]),' in invoices
    assert '("subtotal", ["0.00", "13.00", "50.75"]),' in invoices
    assert '("total", ["-1.00", "12.00", "49.75"]),' in invoices
    assert '("average_line", [None, "13.00", "16.92"]),' in invoices
    assert '("smallest_line", [None, "13.00", "6.25"]),' in invoices
    assert '("largest_line", [None, "13.00", "31.50"]),' in invoices
    assert '({"subtotal_min": "13.00"}, [1, 2]),' in invoices
    assert '({"subtotal_max": "13.00"}, [0, 1]),' in invoices
    posts = files["tests/features/posts/test_totals.py"]
    assert 'VOTES: list[dict[str, Any]] = [\n    {"value": 1},\n    {"value": -1},' in posts
    assert '("upvotes", [0, 1, 2]),' in posts
    assert '("tag_weight", [0, 12, 47]),' in posts
    assert "tags = [await make_tag(session, **values) for values in TAGS]" in posts
    assert "record = await make_post(session, tag_ids=[r.id for r in tags[:count]])" in posts


def test_a_relation_of_an_entity_to_itself_gets_an_alias() -> None:
    text = dedent(
        """\
        version: 0
        app: { name: tree, title: Tree }
        entities:
          Node:
            crud: true
            fields:
              name: { type: string }
              size: { type: integer }
              child_count: { type: integer, computed: count(children) }
            relations:
              parent: { kind: many_to_one, target: Node, inverse: children }
              children: { kind: one_to_many, target: Node, inverse: parent }
        """
    )
    models = files_of(text)["app/models.py"]
    assert "from sqlalchemy.orm import aliased, column_property, configure_mappers" in models
    assert "node_children = aliased(Node)" in models
    assert (
        'totals.total("count", node_children, None, node_children.parent_id == Node.id)'
    ) in models


def test_a_total_needs_a_free_attribute_name_in_the_fastapi_model() -> None:
    text = order_field(
        "count_lines: { type: integer }\n      n: { type: integer, computed: count(lines) }"
    )
    with pytest.raises(GenerationError, match="the attribute 'count_lines'"):
        files_of(text)


FRONT_END_FIELDS = (
    "total: { type: decimal, scale: 2, computed: sum(lines.amount) + fee }\n"
    "      line_count: { type: integer, computed: count(lines) }\n"
    "      debits:\n"
    "        type: decimal\n"
    "        computed: sum(lines.amount)\n"
    "        filter: { kind: debit }\n"
    "      tag_weight: { type: integer, computed: sum(tags.weight) }"
)


def test_the_nextjs_repository_reads_each_total_in_a_subquery() -> None:
    files = files_of(order_field(FRONT_END_FIELDS), nextjs.BINDING)
    repository = files["src/entities/order/api/order-repository.ts"]
    assert 'import { eq } from "drizzle-orm";' in repository
    assert 'import { lineTable, orderTable, orderTagsTable, tagTable } from "@/shared/db";' in (
        repository
    )
    assert 'import { Repository, total } from "@/shared/db/repository";' in repository
    assert (
        "  totals: (record) => ({\n"
        "    // @trace entities.Order.fields.total\n"
        '    sumLinesAmount: total("sum", lineTable, lineTable.amount, '
        "eq(lineTable.orderId, record.id)),\n"
        "    // @trace entities.Order.fields.line_count\n"
        '    countLines: total("count", lineTable, null, eq(lineTable.orderId, record.id)),\n'
    ) in repository
    assert (
        "    debitsSumLinesAmount: total(\n"
        '      "sum",\n'
        "      lineTable,\n"
        "      lineTable.amount,\n"
        "      eq(lineTable.orderId, record.id),\n"
        '      eq(lineTable.kind, "debit"),\n'
        "    ),\n"
    ) in repository
    assert (
        "    sumTagsWeight: total(\n"
        '      "sum",\n'
        "      [tagTable, orderTagsTable],\n"
        "      tagTable.weight,\n"
        "      eq(orderTagsTable.orderId, record.id),\n"
        "      eq(orderTagsTable.tagId, tagTable.id),\n"
        "    ),\n"
    ) in repository
    shared = files["src/shared/db/repository.ts"]
    assert "export function total(" in shared
    assert 'const record = alias(this.table, "record");' in shared
    # An app without totals keeps its repository.
    plain = files_of(order_field(""), nextjs.BINDING)["src/shared/db/repository.ts"]
    assert "function total(" not in plain
    assert "alias" not in plain


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_the_views_compute_the_fields_from_the_totals_of_the_records(binding: Binding) -> None:
    files = files_of(order_field(FRONT_END_FIELDS), binding)
    types = files["src/entities/order/model/types.ts"]
    assert (
        "  // The totals of the related records, for the computed fields (ADR 0034).\n"
        "  sumLinesAmount?: number | null; // @trace entities.Order.fields.total\n"
        "  countLines?: number | null; // @trace entities.Order.fields.line_count\n"
        "  debitsSumLinesAmount?: number | null; // @trace entities.Order.fields.debits\n"
        "  sumTagsWeight?: number | null; // @trace entities.Order.fields.tag_weight\n"
    ) in types
    table = next(v for k, v in files.items() if k.endswith("order-table-view.tsx"))
    assert (
        "compute.round(compute.add(compute.num(row.sumLinesAmount), compute.num(row.fee)), 2)"
    ) in table
    assert "compute.num(row.debitsSumLinesAmount)" in table


def test_the_react_mock_store_computes_the_totals_from_the_related_records() -> None:
    files = files_of(order_field(FRONT_END_FIELDS), react.BINDING)
    api = files["src/entities/order/api/order-api.ts"]
    assert (
        ").withTotals([\n"
        "  { // @trace entities.Order.fields.total begin\n"
        '    key: "sumLinesAmount",\n'
        '    fn: "sum",\n'
        '    target: "Line",\n'
        '    link: "orderId",\n'
        '    field: "amount",\n'
        "  }, // @trace entities.Order.fields.total end\n"
    ) in api
    assert '    filter: [\n      ["kind", "eq", "debit"],\n    ],\n' in api
    assert '    list: "tags",\n    field: "weight",\n' in api
    store = files["src/shared/api/mock-store.ts"]
    assert "withTotals(totals: readonly Total[]): this {" in store
    assert "values[total.key] = totalOf(total, items);" in store
    plain = files_of(order_field(""), react.BINDING)["src/shared/api/mock-store.ts"]
    assert "withTotals" not in plain
    assert "recordsByEntity" not in plain


def test_the_react_app_reads_the_totals_from_the_fastapi_app() -> None:
    text = order_field(FRONT_END_FIELDS).replace(
        "app: { name: shop, title: Shop }", "app: { name: shop, title: Shop, x-react-data: api }"
    )
    files = files_of(text, react.BINDING)
    api = files["src/entities/order/api/order-api.ts"]
    assert '    "line_count": "lineCount",\n' in api
    assert '    "tag_weight": "tagWeight",\n' in api
    assert 'numbers: ["fee", "total", "debits"],' in api
    assert "withTotals" not in api
    types = files["src/entities/order/model/types.ts"]
    assert (
        "  // The computed fields with totals: the FastAPI app sends their values (ADR 0034).\n"
        "  total?: number | null; // @trace entities.Order.fields.total\n"
    ) in types
    table = next(v for k, v in files.items() if k.endswith("order-table-view.tsx"))
    assert "compute.num(row.total)" in table
    assert "compute.add(" not in table


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_a_total_needs_a_free_key_in_the_records_of_the_front_ends(binding: Binding) -> None:
    text = order_field(
        "count_lines: { type: integer }\n      n: { type: integer, computed: count(lines) }"
    )
    with pytest.raises(GenerationError, match="the key 'countLines'"):
        files_of(text, binding)


def test_the_fixture_is_valid() -> None:
    assert validate_definition(load_definition(FIXTURE)) == []
