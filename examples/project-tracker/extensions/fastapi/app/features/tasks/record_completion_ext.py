# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.record_completion file
"""The logic of the operation `record_completion`.

Set the completion time of a task that is done, and clear it for other tasks.

The event `changed` of Task runs the operation after a change of the
status, in the transaction of the change (ADR 0031). This file is the
hand-written code of the project tracker example: the checks copy it
into the app before they generate it (examples/README.md).
"""

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.tasks.enums import TaskStatus
from app.features.tasks.models import Task


async def record_completion(
    session: AsyncSession,
    record: Task,
) -> None:
    """Set the completion time of a done task that has none, or clear it.

    The repository commits the change of the record with the change of
    the status.
    """
    if record.status != TaskStatus.DONE:
        record.completed_at = None
    elif record.completed_at is None:
        record.completed_at = dt.datetime.now(dt.UTC)
