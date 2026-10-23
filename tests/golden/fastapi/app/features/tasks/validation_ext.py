# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual entities.Task file
"""The custom validation of the entity Task.

The create and update operations call `validate` before they store a
record. Add the rules that the field types and options cannot give,
for example a rule for two fields together.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.tasks.models import Task


async def validate(session: AsyncSession, record: Task, *, created: bool) -> None:
    """Check a record before the operation stores it. By default, accept all records.

    The record has the values of the request. `created` is true for a
    new record. To reject the record, raise
    `app.core.errors.ProblemError(422, "<the reason>")`.
    """
    # Add the validation rules of the entity Task here, if it has some.
