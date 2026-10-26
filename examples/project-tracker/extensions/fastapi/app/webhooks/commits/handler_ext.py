# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual webhooks.commits file
"""The logic of the webhook `commits`: POST /webhooks/commits.

The code host reports a commit that refers to a task. The app adds the
commit message to the task as a comment of the author.

This file is the hand-written code of the project tracker example: the
checks copy it into the app before they generate it (examples/README.md).
"""

import datetime as dt
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.i18n import t
from app.features.comments import repository as comments
from app.features.comments.schemas import CommentCreate
from app.features.people.models import Person
from app.features.tasks import repository as tasks
from app.webhooks.commits.models import CommitEvent


async def handle_commits(
    session: AsyncSession,
    event: CommitEvent,
    headers: Mapping[str, str],
) -> None:
    """Add the commit message to the task, as a comment of the person with the email address.

    An unknown task gives 404, and an unknown author 422: the code host
    can then deliver the event again later.
    """
    task = await tasks.get(session, event.task_id)
    author = await session.scalar(select(Person).where(Person.email == event.author_email))
    if author is None:
        message = t("No person has the email address {email}.", email=event.author_email)
        raise ProblemError(422, message)
    body = event.message if event.url is None else f"{event.message}\n\n{event.url}"
    data = CommentCreate(
        body=body[:10000],
        posted_at=dt.datetime.now(dt.UTC),
        task_id=task.id,
        author_id=author.id,
    )
    await comments.add(session, data)
