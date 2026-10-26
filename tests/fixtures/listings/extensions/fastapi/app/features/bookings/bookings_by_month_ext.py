# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.bookings_by_month file
"""The rows of the query `bookings_by_month`.

The count of the bookings and of their nights in each month of a year.

This file is the hand-written code of the fixture tests/fixtures/listings.yaml:
the checks copy it into the app before they generate it.
"""

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.bookings.models import Booking
from app.features.bookings.schemas import BookingsByMonthParams, BookingsByMonthRow


async def bookings_by_month(
    session: AsyncSession,
    params: BookingsByMonthParams,
) -> Sequence[BookingsByMonthRow]:
    """Return one row for each month of the year with a check-in, in the order of the months.

    The nights of a booking count in the month of its check-in.
    """
    start = dt.date(params.year, 1, 1)
    end = dt.date(params.year + 1, 1, 1)
    statement = select(Booking).where(Booking.check_in >= start, Booking.check_in < end)
    months: dict[dt.date, BookingsByMonthRow] = {}
    for booking in await session.scalars(statement):
        month = booking.check_in.replace(day=1)
        row = months.setdefault(month, BookingsByMonthRow(month=month, bookings=0, nights=0))
        row.bookings += 1
        row.nights += (booking.check_out - booking.check_in).days
    return [months[month] for month in sorted(months)]
