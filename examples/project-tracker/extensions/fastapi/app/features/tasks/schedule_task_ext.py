# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.schedule_task file
"""The logic of the operation `schedule_task`.

Set the due date of the task to a number of working days from today.
Weekends and the public holidays of the country are not working days.

This file is the hand-written code of the project tracker example: the
checks copy it into the app before they generate it (examples/README.md).
"""

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.tasks.models import Task
from app.features.tasks.schemas import ScheduleTaskParams
from app.integrations.holidays.client import HolidaysClient


async def schedule_task(
    session: AsyncSession,
    record: Task,
    params: ScheduleTaskParams,
    holidays: HolidaysClient,
) -> Task:
    """Set the due date of the task, and return the task.

    The function gets the public holidays of each year that it counts
    from the API. A holiday counts only if it is in all regions.
    """
    holidays_by_year: dict[int, set[dt.date]] = {}
    day = dt.date.today()
    left = params.working_days
    while left > 0:
        day += dt.timedelta(days=1)
        if day.year not in holidays_by_year:
            found = await holidays.get_public_holidays(day.year, params.country_code)
            holidays_by_year[day.year] = {h.date for h in found if h.global_}
        if day.weekday() < 5 and day not in holidays_by_year[day.year]:
            left -= 1
    record.due_date = day
    return record
