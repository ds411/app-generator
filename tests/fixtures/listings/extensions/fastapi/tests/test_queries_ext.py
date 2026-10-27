"""The tests of the hand-written queries of the fixture tests/fixtures/listings.yaml.

The checks copy this file into the app with the logic of the queries. It
shows that a query endpoint gives a page of the rows of its logic, for its
params (ADR 0045).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_booking, make_listing

pytestmark = pytest.mark.anyio


async def test_a_query_gives_a_page_of_the_records_of_its_params(
    client: AsyncClient, session: AsyncSession
) -> None:
    cheap = await make_listing(session, city="Porto", guests=4, nightly_rate="80.00")
    dear = await make_listing(session, city="Porto", guests=6, nightly_rate="150.00")
    await make_listing(session, city="Porto", guests=2, nightly_rate="60.00")
    await make_listing(session, city="Faro", guests=6, nightly_rate="70.00")
    params = {"city": "Porto", "guests": 4, "limit": 1}

    first = await client.get("/listings/listings-for-guests", params=params)
    second = await client.get("/listings/listings-for-guests", params={**params, "offset": 1})

    assert first.status_code == 200, first.text
    assert first.json()["total"] == 2
    assert [item["id"] for item in first.json()["items"]] == [str(cheap.id)]
    assert [item["id"] for item in second.json()["items"]] == [str(dear.id)]


async def test_a_query_gives_rows_that_are_not_records(
    client: AsyncClient, session: AsyncSession
) -> None:
    listing = str((await make_listing(session)).id)
    for check_in, check_out in (
        ("2031-03-02", "2031-03-06"),
        ("2031-03-10", "2031-03-12"),
        ("2031-05-01", "2031-05-08"),
        ("2032-01-01", "2032-01-03"),
    ):
        await make_booking(session, listing_id=listing, check_in=check_in, check_out=check_out)

    response = await client.get("/bookings/bookings-by-month", params={"year": 2031})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {"month": "2031-03-01", "bookings": 2, "nights": 6},
            {"month": "2031-05-01", "bookings": 1, "nights": 7},
        ],
        "total": 2,
        "limit": 50,
        "offset": 0,
    }


async def test_a_query_gives_the_records_of_a_param_of_a_uuid(
    client: AsyncClient, session: AsyncSession
) -> None:
    listing = str((await make_listing(session)).id)
    other = str((await make_listing(session)).id)
    late = await make_booking(
        session, listing_id=listing, check_in="2031-06-10", check_out="2031-06-12"
    )
    early = await make_booking(
        session, listing_id=listing, check_in="2031-06-01", check_out="2031-06-03"
    )
    await make_booking(session, listing_id=other, check_in="2031-06-01", check_out="2031-06-03")

    response = await client.get("/bookings/bookings-of-listing", params={"listing": listing})

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(early.id), str(late.id)]
