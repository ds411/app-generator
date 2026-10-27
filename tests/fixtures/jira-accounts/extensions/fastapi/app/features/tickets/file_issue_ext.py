# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual operations.file_issue file
"""The logic of the operation `file_issue`.

The hand-written code of the fixture tests/fixtures/jira-accounts.yaml:
it makes an issue in Jira for a ticket without one, or adds a comment to
the issue of the ticket, in the name of the user of the client. The
checks copy it into the app before they generate it.
"""

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.tickets.models import Ticket
from app.integrations.jira.client import JiraClient
from app.integrations.jira.models import Comment, IssueUpdateDetails


async def file_issue(
    session: AsyncSession,
    record: Ticket,
    jira: JiraClient,
) -> None:
    """Make an issue in Jira for the ticket, and keep its key, or add a comment to its issue.

    The generated endpoint commits the session after this function.
    """
    if record.issue_key:
        text: JsonValue = {"type": "text", "text": f"The ticket is still open: {record.title}"}
        paragraph: JsonValue = {"type": "paragraph", "content": [text]}
        document: JsonValue = {"type": "doc", "version": 1, "content": [paragraph]}
        await jira.add_comment(record.issue_key, Comment(body_=document))
        return
    fields: dict[str, JsonValue] = {
        "project": {"key": "SUP"},
        "issuetype": {"name": "Task"},
        "summary": record.title,
    }
    issue = await jira.create_issue(IssueUpdateDetails(fields_=fields))
    record.issue_key = issue.key
