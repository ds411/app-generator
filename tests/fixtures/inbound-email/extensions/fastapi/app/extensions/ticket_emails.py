# @trace:manual entities.Ticket
"""Make a ticket of an inbound email, or count a reply on its ticket.

The hand-written code of the fixture tests/fixtures/inbound-email.yaml:
the logic of each of its webhooks calls `receive_email`. The checks copy
it into the app before they generate it.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.inbound_email import InboundEmail
from app.features.tickets import repository as tickets
from app.features.tickets.models import Ticket
from app.features.tickets.schemas import TicketCreate


async def receive_email(session: AsyncSession, email: InboundEmail) -> None:
    """Make a ticket of a new email, or count a reply on the ticket of the email it answers.

    A reply to an email without a ticket gives 404, and a new email
    without a `Message-ID` gives 422: then the mail service can deliver the
    email again later.
    """
    if email.in_reply_to:
        query = select(Ticket).where(Ticket.message_id == email.in_reply_to)
        ticket = await session.scalar(query)
        if ticket is None:
            raise ProblemError(404, f"No ticket has the email {email.in_reply_to}.")
        ticket.replies += 1
        return
    if email.message_id is None:
        raise ProblemError(422, "A new ticket needs an email with a Message-ID.")
    data = TicketCreate(
        subject=(email.subject or "No subject")[:200],
        requester=email.sender.address,
        message_id=email.message_id,
        body=email.text,
    )
    await tickets.add(session, data)
