"""Custom queries that return a list (ADR 0045): the DSL, the checks, and the code of the
FastAPI, Next.js, and React apps."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.schema import json_schema
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "listings.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Order:
        crud: true
        fields:
          number: { type: string, required: true }
          total: { type: decimal, scale: 2 }
    operations:
    {operations}
    """
)

RECORDS = (
    "  open_orders:\n"
    "    kind: query\n"
    "    entity: Order\n"
    "    params: { number: { type: string, required: true } }\n"
    "    returns: Order"
)
ROWS = (
    "  order_totals:\n"
    "    kind: query\n"
    "    entity: Order\n"
    "    result:\n"
    "      day: { type: date, required: true }\n"
    "      total: { type: decimal, scale: 2 }"
)


def errors(operations: str) -> list[tuple[str, str]]:
    definition = load_definition_text(BASE.replace("{operations}", operations), "app.yaml")
    return [(d.code, d.message) for d in validate_definition(definition)]


def fixture_files(binding: Binding) -> dict[str, str]:
    return {f.path: f.content for f in generate(load_definition(FIXTURE), binding).files}


def scoped_files(binding: Binding) -> dict[str, str]:
    """Return the files of a query of records with a record rule of a role (ADR 0025)."""
    text = BASE.replace("{operations}", RECORDS) + dedent(
        """\
        auth: { user_entity: User, username_field: email }
        access:
          role_field: role
          roles:
            clerk:
              operations: [list_orders, read_order, open_orders]
              records:
                Order: { owner: clerk }
        """
    )
    text = text.replace(
        "      total: { type: decimal, scale: 2 }\n",
        "      total: { type: decimal, scale: 2 }\n"
        "    relations:\n"
        "      clerk: { kind: many_to_one, target: User }\n"
        "  User:\n"
        "    fields:\n"
        "      email: { type: email, required: true, unique: true }\n"
        "      role: { type: enum, values: [clerk] }\n",
    )
    definition = load_definition_text(text, "app.yaml")
    assert [d.message for d in validate_definition(definition)] == []
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_query_returns_records_or_rows() -> None:
    assert errors(f"{RECORDS}\n{ROWS}") == []
    assert [d.message for d in validate_definition(load_definition(FIXTURE))] == []


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (
            "  q: { kind: query, entity: Order }",
            ("missing-key", "A query needs one of 'returns' and 'result'."),
        ),
        (
            "  q: { kind: query, entity: Order, returns: Order, result: { n: { type: integer } } }",
            ("invalid-option", "A query has 'returns' or 'result', not both."),
        ),
        (
            "  q: { kind: query, entity: Order, returns: Order,"
            " params: { offset: { type: url } } }",
            ("reserved-name", "The name 'offset' is a query parameter of the page of each query."),
        ),
        (
            "  q: { kind: query, entity: Order, returns: Order, params: { data: { type: json } } }",
            (
                "unsuitable-field",
                "A param of a query is a query parameter of a URL, which cannot hold a value of "
                "the type 'json'.",
            ),
        ),
        (
            "  q: { kind: query, entity: Order, result: { data: { type: json } } }",
            (
                "unsuitable-field",
                "A view cannot show a value of the type 'json' in a row of a query.",
            ),
        ),
        (
            "  q: { kind: query, entity: Order, result: { n: { type: integer, unique: true } } }",
            ("invalid-option", "'unique' is only for entity fields."),
        ),
        (
            "  q: { kind: query, entity: Order, result: { n: { type: integer, default: 1 } } }",
            ("invalid-option", "'default' is only for entity fields."),
        ),
        (
            "  q: { kind: custom, entity: Order, result: { n: { type: integer } } }",
            ("invalid-option", "'result' is only for 'query' operations."),
        ),
        (
            "  q: { kind: list, entity: Order, params: { n: { type: integer } } }",
            ("invalid-option", "'params' is only for 'custom' and 'query' operations."),
        ),
    ],
    ids=[
        "no-rows",
        "both",
        "page-param",
        "json-param",
        "json-row",
        "unique",
        "default",
        "custom-result",
        "list-params",
    ],
)
def test_the_validator_checks_the_rows_and_the_params_of_a_query(
    operation: str, expected: tuple[str, str]
) -> None:
    assert errors(operation) == [expected]


def test_an_operation_action_cannot_run_a_query() -> None:
    text = BASE.replace("{operations}", RECORDS) + dedent(
        """\
        pages:
          orders: { path: /orders, title: Orders, content: { view: order_table } }
        ui:
          views:
            order_table:
              kind: table
              entity: Order
              columns: { number: {} }
              row_actions:
                open: { kind: operation, operation: open_orders, label: Open }
        """
    )
    definition = load_definition_text(text, "app.yaml")
    assert [(d.code, d.message) for d in validate_definition(definition)] == [
        (
            "unsuitable-operation",
            "The operation 'open_orders' is a query: it gives rows, and an action does not "
            "show them.",
        )
    ]


def test_the_schema_has_the_kind_query_and_the_result() -> None:
    schema = json_schema()["$defs"]
    assert "query" in schema["OperationKind"]["enum"]
    assert "result" in schema["Operation"]["properties"]


def test_the_fastapi_query_is_a_get_endpoint_with_a_page_of_the_rows() -> None:
    files = fixture_files(fastapi.BINDING)
    query = files["app/features/listings/listings_for_guests_gen.py"]
    assert "class ListingsForGuestsQuery(ListingsForGuestsParams, PageParams):" in query
    assert '@router.get(\n    "/listings-for-guests",\n' in query
    assert "responses=problem_responses(422, 501)," in query
    assert ") -> Page[ListingRead]:" in query
    assert "    rows = await listings_for_guests(session, query)\n" in query
    assert "    page = rows[query.offset : query.offset + query.limit]\n" in query
    assert "scope" not in query
    gap = files["app/features/listings/listings_for_guests_ext.py"]
    assert "# @trace:gap operations.listings_for_guests file" in gap
    assert ") -> Sequence[Listing]:" in gap
    assert 'raise NotImplementedError("operations.listings_for_guests")' in gap
    schemas = files["app/features/bookings/schemas.py"]
    assert (
        "# @trace operations.bookings_by_month\n"
        "class BookingsByMonthRow(ReadModel):\n"
        '    """A row of the query `bookings_by_month` (ADR 0045)."""\n'
        "\n"
        "    # @trace operations.bookings_by_month.result.month\n"
        '    month: dt.date = Field(title="Month")\n'
    ) in schemas
    rows = files["app/features/bookings/bookings_by_month_ext.py"]
    assert ") -> Sequence[BookingsByMonthRow]:" in rows
    pagination = files["app/core/pagination.py"]
    assert "class PageQuery(PageParams):" in pagination
    tests = files["tests/features/bookings/test_bookings_by_month.py"]
    assert "async def test_bookings_by_month_gives_501_until_it_has_its_logic(" in tests
    assert "async def test_bookings_by_month_rejects_a_page_that_is_not_valid(" in tests


def test_the_record_rules_apply_to_the_records_of_a_query() -> None:
    query = scoped_files(fastapi.BINDING)["app/features/orders/open_orders_gen.py"]
    assert 'Scope = Annotated[RecordScope | None, Depends(scope_of("read"))]' in query
    assert "from app.features.orders import repository\n" in query
    assert (
        "    shown = await repository.visible(session, [row.id for row in rows], scope)\n"
        "    rows = [row for row in rows if row.id in shown]\n"
    ) in query
    action = scoped_files(nextjs.BINDING)["src/features/open-orders/api/open-orders.gen.ts"]
    assert "const shown = await orderRepository.visible(" in action
    assert 'await recordScope("Order", "read"),' in action
    assert '{ operation: "open_orders" },' in action
    repository = scoped_files(nextjs.BINDING)["src/shared/db/repository.ts"]
    assert "async visible(ids: string[], scope: RecordScope | null): Promise<Set<string>> {" in (
        repository
    )
    mock = scoped_files(react.BINDING)["src/features/open-orders/api/open-orders.gen.ts"]
    assert 'requireOperation("open_orders");' in mock
    assert (
        "const shown = new Set((await orderApi.list()).items.map((record) => record.id));" in mock
    )


def test_the_front_ends_give_a_page_of_the_rows_of_the_extension_file() -> None:
    files = fixture_files(nextjs.BINDING)
    action = files["src/features/bookings-by-month/api/bookings-by-month.gen.ts"]
    assert '"use server";' in action
    assert (
        "      const rows = await bookingsByMonth(bookingsByMonthParamsSchema.parse(params));\n"
        "      return pageOfRows(rows, pageSchema.parse(page));\n"
    ) in action
    api = files["src/features/bookings-by-month/api/bookings-by-month-api.ts"]
    assert (
        "export async function bookingsByMonth(params: BookingsByMonthParams, page: RowsPage = "
        "FIRST_ROWS): Promise<ListResult<BookingsByMonthRow>> {"
    ) in api
    gap = files["src/features/bookings-by-month/api/bookings-by-month.ext.ts"]
    assert 'import "server-only";' in gap
    assert "Promise<BookingsByMonthRow[]>" in gap
    types = files["src/entities/booking/model/types.ts"]
    assert "export type BookingsByMonthRow = {" in types
    assert "  month: string; // @trace operations.bookings_by_month.result.month" in types
    shared = files["src/shared/api/types.ts"]
    assert "export function pageOfRows<T>(" in shared
    mock = fixture_files(react.BINDING)
    function = mock["src/features/listings-for-guests/api/listings-for-guests.gen.ts"]
    assert "return pageOfRows(await listingsForGuestsExt(params), page);" in function
    assert "src/features/listings-for-guests/api/listings-for-guests.ext.ts" in mock


def test_the_react_app_with_the_fastapi_app_calls_the_endpoint_of_the_query() -> None:
    text = FIXTURE.read_text().replace("app:\n", "app:\n  x-react-data: api\n", 1)
    definition = load_definition_text(text, "app.yaml")
    files = {f.path: f.content for f in generate(definition, react.BINDING).files}
    rows = files["src/features/bookings-by-month/api/bookings-by-month.gen.ts"]
    assert 'const result = await bookingApi.rows("/bookings-by-month", {' in rows
    assert '    "year": params.year,' in rows
    assert '      bookings: item["bookings"],' in rows
    records = files["src/features/listings-for-guests/api/listings-for-guests.gen.ts"]
    assert "items: result.items.map((item) => listingApi.fromJson(item))" in records
    assert "src/features/listings-for-guests/api/listings-for-guests.ext.ts" not in files
    store = files["src/shared/api/http-store.ts"]
    assert 'search.set("offset", String((page.page - 1) * page.pageSize));' in store


def test_an_app_without_queries_has_no_helpers_of_the_rows() -> None:
    definition = load_definition_text(BASE.replace("{operations}", "  {}"), "app.yaml")
    for binding in (nextjs.BINDING, react.BINDING):
        files = {f.path: f.content for f in generate(definition, binding).files}
        assert "pageOfRows" not in files["src/shared/api/types.ts"]
        assert "pageOfRows" not in files["src/shared/api/index.ts"]
