# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.sync_calendar file
"""The logic of the operation `sync_calendar`.

The hand-written code of the fixture tests/fixtures/api-connections.yaml:
it counts the events of the user of the client. The checks copy it into
the app before they generate it.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.calendars.models import Calendar
from app.integrations.calendar.client import CalendarClient


async def sync_calendar(
    session: AsyncSession,
    record: Calendar,
    calendar: CalendarClient,
) -> None:
    """Count the events of the user of the client on the record.

    The generated endpoint commits the session after this function.
    """
    events = await calendar.list_events(limit=100)
    record.events = len(events.items)
