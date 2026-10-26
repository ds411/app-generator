"""The test of the hand-written router of the project tracker example.

The checks copy this file into the app with `app/extensions/routers_ext.py`
(examples/README.md). It shows that `app/main.py` includes the routers of
the extension file.
"""

import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_task

pytestmark = pytest.mark.anyio


async def test_the_feed_has_the_due_dates_of_the_open_tasks(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_task(session, title="Write the plan, v2", status="todo", due_date="2026-11-02")
    await make_task(session, title="Ship", status="done", due_date="2026-11-03")
    await make_task(session, title="Later", status="todo", due_date=None)

    response = await client.get("/feeds/due-dates.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "X-Request-ID" in response.headers
    lines = response.text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR"
    assert "DTSTART;VALUE=DATE:20261102" in lines
    assert "SUMMARY:Write the plan\\, v2" in lines
    assert lines.count("BEGIN:VEVENT") == 1
    assert dt.date(2026, 11, 3).strftime("%Y%m%d") not in response.text
