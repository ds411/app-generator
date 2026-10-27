"""Tests of the available filters (ADR 0047): the records without a related record in the days."""

from textwrap import dedent, indent

import pytest

from appgen.dsl import load_definition_text, validate_definition
from appgen.dsl.ui.views import AvailableFilter
from appgen.gen import find_binding, generate

STAYS = dedent(
    """\
    version: 0
    app: { name: stays, title: Stays }
    entities:
      Listing:
        crud: { operations: [list, read] }
        display_field: title
        fields:
          title: { type: string, required: true }
        relations:
          bookings: { kind: one_to_many, target: Booking, inverse: listing }
      Booking:
        crud: { operations: [list, create] }
        display_field: guest
        fields:
          guest: { type: string, required: true }
          check_in: { type: date, required: true }
          check_out: { type: date, required: true }
        relations:
          listing: { kind: many_to_one, target: Listing, required: true, inverse: bookings }
        rules:
          after_check_in:
            kind: compare
            field: check_out
            op: gt
            other: check_in
            message: The check-out must be after the check-in.
          no_double_booking:
            kind: no_overlap
            start: check_in
            end: check_out
            scope: [listing]
            message: The listing has another booking on these dates.
      Speaker:
        crud: { operations: [list] }
        display_field: name
        fields:
          name: { type: string, required: true }
        relations:
          talks: { kind: many_to_many, target: Talk, inverse: speakers }
      Talk:
        crud: { operations: [list, create] }
        display_field: title
        fields:
          title: { type: string, required: true }
          starts_at: { type: datetime }
          ends_at: { type: datetime }
        relations:
          speakers: { kind: many_to_many, target: Speaker, inverse: talks }
        rules:
          one_room:
            kind: no_overlap
            start: starts_at
            end: ends_at
            message: The room has another talk at this time.
    pages:
      free: { path: /free, title: Free listings, content: { view: free_listings } }
      speakers: { path: /speakers, title: Speakers, content: { view: free_speakers } }
    ui:
      views:
        free_listings:
          kind: table
          entity: Listing
          columns: { title: {} }
          filters:
            dates: { kind: available, rule: bookings.no_double_booking, label: Dates }
        free_speakers:
          kind: cards
          entity: Speaker
          filters:
            free: { kind: available, rule: talks.one_room }
    """
)
API = STAYS.replace(
    "app: { name: stays, title: Stays }", "app: { name: stays, title: Stays, x-react-data: api }"
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files(text: str, binding: str) -> dict[str, str]:
    result = generate(load_definition_text(text, "app.yaml"), find_binding(binding))
    return {f.path: f.content for f in result.files}


def test_an_available_filter_is_valid() -> None:
    assert codes(STAYS) == []
    definition = load_definition_text(STAYS, "app.yaml")
    view = definition.ui.views["free_listings"] if definition.ui else None
    assert view is not None
    found = view.filters["dates"]  # type: ignore[union-attr]
    assert isinstance(found, AvailableFilter)
    assert (found.relation, found.rule_name) == ("bookings", "no_double_booking")


FILTER = "ui.views.free_listings.filters.dates"


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("bokings.no_double_booking", "unknown-reference"),
        ("bookings.no_such_rule", "unknown-reference"),
        # A compare rule has no range.
        ("bookings.after_check_in", "invalid-option"),
    ],
)
def test_the_rule_of_an_available_filter_is_a_no_overlap_rule_of_a_relation(
    rule: str, expected: str
) -> None:
    text = STAYS.replace("rule: bookings.no_double_booking", f"rule: {rule}")
    assert codes(text) == [(expected, FILTER)]


def test_the_relation_of_an_available_filter_goes_to_many_records() -> None:
    view = dedent(
        """\
            booking_table:
              kind: table
              entity: Booking
              columns: { guest: {} }
              filters:
                free: { kind: available, rule: listing.no_double_booking }
        """
    )
    text = STAYS.replace("ui:\n  views:\n", "ui:\n  views:\n" + indent(view, "    "))
    definition = load_definition_text(text, "app.yaml")
    [diagnostic] = validate_definition(definition)
    assert (diagnostic.code, diagnostic.element_id) == (
        "unsuitable-field",
        "ui.views.booking_table.filters.free",
    )
    assert "'Booking.listing' is many_to_one" in diagnostic.message


def test_the_fastapi_list_endpoint_keeps_the_records_without_a_range_in_the_days() -> None:
    app = files(STAYS, "fastapi")
    listings = app["app/features/listings/list_listings.py"]
    assert "    # @trace ui.views.free_listings.filters.dates\n    bookings_free_from: dt.date" in (
        listings
    )
    # On date fields, the days are the range of a new booking.
    assert (
        "        high = range_end(query.bookings_free_from, query.bookings_free_to)\n" in listings
    )
    assert "~Listing.bookings.any(and_(Booking.check_in < high, Booking.check_out > low))" in (
        listings
    )
    assert "def range_end(" in app["app/core/pagination.py"]
    # On date-time fields, they are whole days.
    speakers = app["app/features/speakers/list_speakers.py"]
    assert "        low = day_start(query.talks_free_from)\n" in speakers
    assert "high = day_start(query.talks_free_to or query.talks_free_from, 1)" in speakers
    assert "~Speaker.talks.any(and_(Talk.starts_at < high, Talk.ends_at > low))" in speakers
    test = app["tests/features/listings/test_list_listings_query.py"]
    assert "async def test_list_listings_filters_by_the_free_days_of_bookings(" in test
    assert "await make_booking(session, listing_id=busy, check_in=" in test
    test = app["tests/features/speakers/test_list_speakers_query.py"]
    assert "busy = str((await make_speaker(session, talk_ids=[str(related.id)])).id)" in test


def test_the_nextjs_app_reads_the_ranges_of_all_related_records() -> None:
    app = files(STAYS, "nextjs")
    repository = app["src/entities/listing/api/listing-repository.ts"]
    assert "export const listingRangeQueries: Record<string, () => Promise<OwnerRange[]>>" in (
        repository
    )
    assert (
        ".select({ id: bookingTable.listingId, start: bookingTable.checkIn, "
        "end: bookingTable.checkOut })"
    ) in repository
    assert "return rows.map((row): OwnerRange => [row.id, row.start, row.end]);" in repository
    speakers = app["src/entities/speaker/api/speaker-repository.ts"]
    assert "row.start?.toISOString() ?? null" in speakers
    assert ".innerJoin(talkTable, eq(" in speakers
    actions = app["src/entities/listing/api/listing-actions.ts"]
    assert "export async function listListingRangesAction(key: string)" in actions
    api = app["src/entities/listing/api/listing-api.ts"]
    assert 'export async function listingRanges(key: "bookings.no_double_booking")' in api
    view = app["src/widgets/free-listings/ui/free-listings-view.tsx"]
    assert 'listingRanges("bookings.no_double_booking"),' in view
    assert "isFree(lookups.bookingsNoDoubleBooking.get(row.id), filters.dates, true)" in view
    assert "<DateRangeFilter" in view
    query = app["src/shared/lib/query.ts"]
    assert "export function isFree(" in query and "export function rangesById(" in query


def test_the_react_mock_store_reads_the_ranges_of_the_related_store() -> None:
    app = files(STAYS, "react")
    api = app["src/entities/speaker/api/speaker-api.ts"]
    assert '    list: "talks",\n' in api
    assert "return speakerApi.ranges(RANGES[key]);" in api
    assert "async ranges(spec: RangeSpec" in app["src/shared/api/mock-store.ts"]
    view = app["src/widgets/free-speakers/ui/free-speakers-view.tsx"]
    assert "isFree(lookups.talksOneRoom.get(row.id), filters.free, false)" in view


def test_the_react_app_of_the_api_sends_the_days() -> None:
    app = files(API, "react")
    view = app["src/widgets/free-listings/ui/free-listings-view.tsx"]
    assert "bookings_free_from: filters.dates.from," in view
    assert "bookings_free_to: filters.dates.to," in view
    assert "isFree" not in view
    assert "Ranges" not in app["src/entities/listing/api/listing-api.ts"]
