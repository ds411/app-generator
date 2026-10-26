// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.send_dunning file
import "server-only";

import type { Invoice, SendDunningParams } from "@/entities/invoice";
import { invoiceRepository } from "@/entities/invoice/server";

/**
 * Send a dunning letter to the customer.
 *
 * The hand-written operation of the jobs test (scripts/jobs_test.py): it
 * sets the status `sent`. For an invoice whose number starts with FAIL, it
 * sets the status `paid` and then fails, so that the test sees the roll
 * back of the run.
 */
export async function sendDunning(record: Invoice, params: SendDunningParams): Promise<void> {
  if (record.number.startsWith("FAIL")) {
    await invoiceRepository.update(record.id, { status: "paid" });
    throw new Error(`The test fails the dunning letter ${params.level} of ${record.number}.`);
  }
  await invoiceRepository.update(record.id, { status: "sent" });
}
