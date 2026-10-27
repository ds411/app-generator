# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.listings_for_guests file
"""The rows of the query `listings_for_guests`.

The listings of a city with room for a count of guests, the cheapest first.

This file is the hand-written code of the fixture tests/fixtures/listings.yaml:
the checks copy it into the app before they generate it.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.listings.models import Listing
from app.features.listings.schemas import ListingsForGuestsParams


async def listings_for_guests(
    session: AsyncSession,
    params: ListingsForGuestsParams,
) -> Sequence[Listing]:
    """Return the listings of the city with room for the guests, the cheapest first."""
    statement = select(Listing).where(Listing.city == params.city)
    if params.guests is not None:
        statement = statement.where(Listing.guests >= params.guests)
    statement = statement.order_by(Listing.nightly_rate, Listing.title)
    return (await session.scalars(statement)).all()
