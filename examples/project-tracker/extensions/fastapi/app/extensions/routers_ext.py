# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual app file
"""The hand-written routers of the app.

`app/main.py` includes each router of `ROUTERS` after the generated
routers, so the middleware of the app applies to them too.

This file is the hand-written code of the project tracker example: the
checks copy it into the app before they generate it (examples/README.md).
The router gives a calendar feed (iCalendar, RFC 5545) of the due dates
of the open tasks, which the definition does not describe.
"""

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import select

from app.core.db import SessionDep
from app.features.tasks.enums import TaskStatus
from app.features.tasks.models import Task

router = APIRouter(prefix="/feeds", tags=["feeds"])


def _text(value: str) -> str:
    """Escape a text value of iCalendar (RFC 5545, section 3.3.11)."""
    for char in ("\\", ";", ","):
        value = value.replace(char, "\\" + char)
    return value.replace("\n", "\\n")


@router.get("/due-dates.ics", response_class=Response)
async def due_dates(session: SessionDep) -> Response:
    """Give an all-day event on the due date of each task that is not done."""
    tasks = await session.scalars(
        select(Task)
        .where(Task.due_date.is_not(None), Task.status != TaskStatus.DONE)
        .order_by(Task.due_date, Task.id)
    )
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//appgen//project-tracker//EN"]
    for task in tasks:
        assert task.due_date is not None
        lines += [
            "BEGIN:VEVENT",
            f"UID:{task.id}@project-tracker",
            f"DTSTAMP:{task.due_date:%Y%m%d}T000000Z",
            f"DTSTART;VALUE=DATE:{task.due_date:%Y%m%d}",
            f"SUMMARY:{_text(task.title)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar")


ROUTERS: list[APIRouter] = [router]
"""The hand-written routers, in the order that the app includes them."""
