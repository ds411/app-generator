"""The views of the rows of a query (ADR 0045): the DSL, the checks, and the code of the
Next.js and React views."""

from pathlib import Path

import pytest

from appgen.bindings import nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.diagnostics import DefinitionError
from appgen.dsl.schema import json_schema
from appgen.dsl.ui.views import QueryCalendarView, QueryCardsView, QueryTableView
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "listings.yaml"
TEXT = FIXTURE.read_text()


def with_view(view: str, page: str = "") -> str:
    """Return the fixture with one more view, and a page of it at `/extra`."""
    text = TEXT.replace("ui:\n  views:\n", "ui:\n  views:\n" + view, 1)
    page = page or "  extra: { path: /extra, title: Extra, content: { view: extra } }\n"
    return text.replace("pages:\n", "pages:\n" + page, 1)


def errors(view: str, page: str = "") -> list[tuple[str, str]]:
    definition = load_definition_text(with_view(view, page), "app.yaml")
    return [(d.code, d.message) for d in validate_definition(definition)]


def files(binding: Binding, text: str = TEXT) -> dict[str, str]:
    definition = load_definition_text(text, str(FIXTURE))
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_view_takes_a_query_in_place_of_an_entity() -> None:
    definition = load_definition(FIXTURE)
    assert definition.ui is not None
    views = definition.ui.views
    assert isinstance(views["stay_table"], QueryTableView)
    assert isinstance(views["month_cards"], QueryCardsView)
    assert isinstance(views["listing_calendar"], QueryCalendarView)
    assert [d.message for d in validate_definition(definition)] == []


def test_the_schema_has_the_views_of_a_query() -> None:
    schema = json_schema()["$defs"]
    assert {"QueryTableView", "QueryCardsView", "QueryCalendarView", "QueryFilter"} <= set(schema)


@pytest.mark.parametrize(
    ("view", "message"),
    [
        (
            "    extra: { kind: table, query: listings_for_guests, entity: Listing,"
            " columns: { title: {} } }\n",
            "A view has an entity or a query, not both (key 'entity').",
        ),
        (
            "    extra: { kind: table, query: listings_for_guests, columns: { title: {} },"
            " sort: { field: title } }\n",
            "A view of a query has no sort: the query gives the order of the rows (key 'sort').",
        ),
        (
            "    extra: { kind: table, query: listings_for_guests, columns: { title: {} },"
            " order_field: position }\n",
            "A view of a query has no manual order: the query gives the order of the rows "
            "(key 'order_field').",
        ),
        (
            "    extra: { kind: board, query: listings_for_guests }\n",
            "The kind 'board' of a view with 'query' is not valid. Expected 'table', 'cards', "
            "'calendar'.",
        ),
    ],
    ids=["entity", "sort", "order_field", "kind"],
)
def test_the_loader_rejects_the_keys_of_other_views(view: str, message: str) -> None:
    with pytest.raises(DefinitionError) as error:
        load_definition_text(with_view(view), "app.yaml")
    assert message in str(error.value)


TABLE = "    extra:\n      kind: table\n      query: listings_for_guests\n"
CARDS = "    extra:\n      kind: cards\n      query: bookings_by_month\n"
CALENDAR = "    extra:\n      kind: calendar\n      query: bookings_of_listing\n"


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        (
            "    extra: { kind: table, query: list_listings, columns: { title: {} } }\n",
            (
                "unsuitable-operation",
                "The operation 'list_listings' is a list operation. A view shows the rows of "
                "an operation with 'kind: query'.",
            ),
        ),
        (
            TABLE + "      filters: { city: {}, rooms: {} }\n      columns: { title: {} }\n",
            ("unknown-reference", "The query 'listings_for_guests' has no param 'rooms'."),
        ),
        (
            TABLE + "      params: { city: Lisbon }\n      filters: { city: {} }\n"
            "      columns: { title: {} }\n",
            (
                "invalid-option",
                "The param 'city' gets its value from 'params' and from the filter 'city'. A "
                "param gets one value.",
            ),
        ),
        (
            TABLE + "      filters: { city: {}, guests: { default: many } }\n"
            "      columns: { title: {} }\n",
            (
                "invalid-value",
                "The default \"many\" of the filter 'guests' is not valid: the param has the "
                "type 'integer', which needs an integer.",
            ),
        ),
        (
            TABLE + "      params: { city: $page.city }\n      columns: { title: {} }\n",
            (
                "invalid-value",
                "The value '$page.city' of the param 'city' is not valid. A value that starts "
                "with '$' must be '$route.<name>', a path parameter of the page.",
            ),
        ),
        (
            TABLE + "      filters: { guests: {} }\n      columns: { title: {} }\n",
            ("missing-key", "The query 'listings_for_guests' needs the param 'city'."),
        ),
        (
            TABLE + "      filters: { city: {} }\n      columns: { titel: {} }\n",
            (
                "unknown-reference",
                "The rows of the query 'listings_for_guests' are records of 'Listing', which "
                "has no field 'titel'.",
            ),
        ),
        (
            TABLE + "      filters: { city: {} }\n      columns: { bookings: {} }\n",
            (
                "unsuitable-field",
                "A view of a query shows the fields of its records, but 'bookings' is a "
                "relation of 'Listing'.",
            ),
        ),
        (
            TABLE + "      filters: { city: {} }\n      columns: { city: { format: currency } }\n",
            (
                "unsuitable-field",
                "The format 'currency' does not suit the field 'city' (string) of the rows of "
                "'listings_for_guests'. It needs one of: decimal, integer.",
            ),
        ),
        (
            TABLE + "      filters: { city: {} }\n      columns: { title: {} }\n"
            "      pagination: { mode: scroll }\n",
            (
                "invalid-option",
                "The mode 'scroll' is for the tables and the card lists of entities.",
            ),
        ),
        (
            CARDS + "      filters: { year: {} }\n      card: { title: month, fields: [nigths] }\n",
            (
                "unknown-reference",
                "The rows of the query 'bookings_by_month' have no field 'nigths' in 'result'.",
            ),
        ),
        (
            "    extra:\n      kind: calendar\n      query: bookings_by_month\n"
            "      filters: { year: {} }\n      start: month\n      link: listing_detail\n",
            (
                "missing-key",
                "The rows of the query 'bookings_by_month' are not records, so a calendar of "
                "them needs 'label'.",
            ),
        ),
        (
            CALENDAR + "      filters: { listing: {} }\n      start: guest\n",
            (
                "unsuitable-field",
                "The start of a calendar must be a date or a date-time field, but 'guest' has "
                "the type 'string'.",
            ),
        ),
    ],
    ids=[
        "not-a-query",
        "unknown-param",
        "two-values",
        "bad-default",
        "bad-route",
        "required-param",
        "unknown-field",
        "relation",
        "format",
        "scroll",
        "unknown-result-field",
        "calendar-label",
        "calendar-start",
    ],
)
def test_the_validator_checks_the_query_the_params_and_the_fields(
    view: str, expected: tuple[str, str]
) -> None:
    assert expected in errors(view)


def test_a_link_opens_the_page_of_a_record() -> None:
    view = CARDS.replace("kind: cards", "kind: calendar") + (
        "      filters: { year: {} }\n      start: month\n      label: bookings\n"
        "      link: listing_detail\n"
    )
    assert errors(view) == [
        (
            "invalid-option",
            "A link opens the page of a record, but the rows of the query 'bookings_by_month' "
            "are not records.",
        )
    ]


def test_the_page_of_a_view_of_a_query_has_its_path_parameters_and_no_entity() -> None:
    view = CALENDAR + "      params: { listing: $route.id }\n      start: check_in\n"
    page = "  extra: { path: /extra, title: Extra, entity: Listing, content: { view: extra } }\n"
    assert errors(view, page) == [
        (
            "unsuitable-view",
            "The view 'extra' shows the rows of a query, but the page shows 'Listing'.",
        ),
        (
            "unsuitable-view",
            "The view 'extra' gives the parameter 'listing' the path parameter 'id' "
            "('$route.id'), but the path '/extra' does not have it.",
        ),
    ]


def test_a_tab_cannot_show_a_view_of_a_query() -> None:
    text = TEXT.replace(
        "    stay_table:\n",
        "    listing_tabs:\n"
        "      kind: detail\n"
        "      entity: Listing\n"
        "      tabs:\n"
        "        stays: { relation: bookings, view: stay_table }\n"
        "    stay_table:\n",
        1,
    )
    definition = load_definition_text(text, "app.yaml")
    assert [(d.code, d.message) for d in validate_definition(definition)] == [
        (
            "unsuitable-view",
            "The view 'stay_table' shows the rows of a query. A list of records needs a view of "
            "an entity.",
        )
    ]


def test_the_nextjs_view_runs_the_server_action_of_the_query_for_its_filters() -> None:
    generated = files(nextjs.BINDING)
    view = generated["src/widgets/stay-table/ui/stay-table-view.tsx"]
    assert 'import { listingsForGuests } from "@/features/listings-for-guests";' in view
    assert (
        "function paramsOf(filters: Filters): ListingsForGuestsParams | null {\n"
        '  if (filters.city.trim() === "") return null;\n'
        "  return {\n"
        "    city: filters.city.trim(),\n"
        '    guests: filters.guests.trim() === "" ? null : Number(filters.guests.trim()),\n'
        "  };\n"
        "}\n"
    ) in view
    assert ": listingsForGuests(params, { page: pages.page, pageSize: pages.pageSize })," in view
    assert "server={{ ...pages, total: resource.data.total, onChange: setPages }}" in view
    assert '<ParamFilter label="City" type="text" required value={filters.city}' in view
    assert 'href={pageHref("listingDetail", { id: String(item.id) })}' in view
    page = generated["src/pages/booking-months/ui/booking-months-page.tsx"]
    assert "  const route = useParams();\n" in page
    assert "<MonthCardsView route={route} />" in page
    assert "src/shared/ui/filters/param-filter.tsx" in generated


def test_the_react_view_reads_the_path_parameters_of_the_page() -> None:
    generated = files(react.BINDING)
    cards = generated["src/widgets/month-cards/ui/month-cards-view.tsx"]
    assert '    year: Number(route.year ?? ""),\n' in cards
    assert "<CardTitle" in cards and '{formatValue(item.month, "date")}' in cards
    calendar = generated["src/widgets/listing-calendar/ui/listing-calendar-view.tsx"]
    assert "const PAGE_SIZE = 200;" in calendar
    assert "const result = await bookingsOfListing(params, { page, pageSize: PAGE_SIZE });" in (
        calendar
    )
    assert 'initialMode="month"' in calendar
    page = generated["src/pages/listing-calendar/ui/listing-calendar-page.tsx"]
    assert "<ListingCalendarView route={route} />" in page


def test_with_the_fastapi_app_the_view_of_a_calendar_keeps_the_shown_days() -> None:
    text = TEXT.replace("app:\n", "app:\n  x-react-data: api\n", 1)
    path = "src/widgets/listing-calendar/ui/listing-calendar-view.tsx"
    calendar = files(react.BINDING, text)[path]
    assert "const [anchor, setAnchor] = useState(() => startOfDay(new Date()));" in calendar
    assert "onAnchorChange={setAnchor}" in calendar


def test_the_filters_suit_the_types_of_the_params() -> None:
    text = TEXT.replace(
        "  bookings_by_month:\n",
        "  search_listings:\n"
        "    kind: query\n"
        "    entity: Listing\n"
        "    params:\n"
        "      kind: { type: enum, values: [home, room], required: true }\n"
        "      since: { type: date }\n"
        "      at: { type: datetime }\n"
        "      pets: { type: boolean }\n"
        "    returns: Listing\n"
        "  bookings_by_month:\n",
        1,
    ).replace(
        "    stay_table:\n",
        "    search_table:\n"
        "      kind: table\n"
        "      query: search_listings\n"
        "      filters: { kind: { default: home }, since: {}, at: {}, pets: {} }\n"
        "      columns: { title: {} }\n"
        "    stay_table:\n",
        1,
    )
    text = text.replace(
        "pages:\n",
        "pages:\n  search: { path: /search, title: Search, content: { view: search_table } }\n",
        1,
    )
    view = files(react.BINDING, text)["src/widgets/search-table/ui/search-table-view.tsx"]
    assert '  kind: "home", // @trace ui.views.search_table.filters.kind' in view
    assert '    kind: filters.kind as SearchListingsParams["kind"],' in view
    assert (
        '    at: filters.at.trim() === "" ? null : new Date(filters.at.trim()).toISOString(),'
        in view
    )
    assert "    pets: filters.pets ? true : null," in view
    assert '{ value: "room", label: "Room" },' in view
    assert '<ParamFilter label="Since" type="date"' in view
    assert '<ParamFilter label="At" type="datetime-local"' in view
    assert "<BooleanFilter" in view and "<SelectFilter" in view
