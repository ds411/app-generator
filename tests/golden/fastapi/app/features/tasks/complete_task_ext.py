# Created by appgen once. appgen never changes or deletes this file.
# @trace:gap operations.complete_task file
"""The logic of the operation `complete_task`."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.tasks.models import Task
from app.features.tasks.schemas import CompleteTaskParams


async def complete_task(
    session: AsyncSession,
    record: Task,
    params: CompleteTaskParams,
) -> Task:
    """Run the operation on a record, with the params of the request.

    The generated endpoint commits the session after this function.
    Return the Task record that the endpoint returns.
    """
    # TODO(appgen): write the logic of the operation complete_task.
    raise NotImplementedError("operations.complete_task")
