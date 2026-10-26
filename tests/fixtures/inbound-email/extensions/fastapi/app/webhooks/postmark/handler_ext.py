# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual webhooks.postmark file
"""The logic of the webhook `postmark`: POST /webhooks/postmark.

The hand-written code of the fixture tests/fixtures/inbound-email.yaml.
"""

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.inbound_email import InboundEmail
from app.extensions.ticket_emails import receive_email


async def handle_postmark(
    session: AsyncSession,
    event: InboundEmail,
    headers: Mapping[str, str],
) -> None:
    """Make a ticket of the email, or count a reply (`app/extensions/ticket_emails.py`)."""
    await receive_email(session, event)
