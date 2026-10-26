// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual webhooks.mailgun file
import "server-only";

import { ticketRepository } from "@/entities/ticket/server";
import { type InboundEmail, WebhookError } from "@/shared/webhooks";

/**
 * Make a ticket of a new email, or count a reply on the ticket of the email that it
 * answers. A reply to an email without a ticket gives 404, and a new email without a
 * `Message-ID` gives 422: then the mail service can deliver the email again later.
 *
 * The hand-written code of the fixture tests/fixtures/inbound-email.yaml. The three
 * webhooks of the fixture have the same logic.
 */
export async function handleMailgun(email: InboundEmail, _headers: Headers): Promise<void> {
  if (email.inReplyTo === null) {
    if (email.messageId === null) {
      throw new WebhookError(422, "A new ticket needs an email with a Message-ID.");
    }
    await ticketRepository.create({
      subject: (email.subject || "No subject").slice(0, 200),
      requester: email.sender.address,
      messageId: email.messageId,
      body: email.text,
    });
    return;
  }
  const found = await ticketRepository.list({
    filters: [{ field: "messageId", op: "eq", value: email.inReplyTo }],
    page: 1,
    pageSize: 1,
  });
  const [ticket] = found.items;
  if (ticket === undefined) {
    throw new WebhookError(404, `No ticket has the email ${email.inReplyTo}.`);
  }
  await ticketRepository.update(ticket.id, { replies: ticket.replies + 1 });
}
