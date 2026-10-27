# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.bookings_of_listing file
"""The rows of the query `bookings_of_listing`.

The bookings of a listing, by check-in.

This file is the hand-written code of the fixture tests/fixtures/listings.yaml:
the checks copy it into the app before they generate it.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.bookings.models import Booking
from app.features.bookings.schemas import BookingsOfListingParams


async def bookings_of_listing(
    session: AsyncSession,
    params: BookingsOfListingParams,
) -> Sequence[Booking]:
    """Return the bookings of the listing, by check-in."""
    statement = (
        select(Booking)
        .where(Booking.listing_id == params.listing)
        .order_by(Booking.check_in, Booking.guest)
    )
    return (await session.scalars(statement)).all()
