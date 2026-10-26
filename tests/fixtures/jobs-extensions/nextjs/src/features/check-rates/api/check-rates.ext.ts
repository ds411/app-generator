// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.check_rates file
import "server-only";

import type { Invoice } from "@/entities/invoice";
import { invoiceRepository } from "@/entities/invoice/server";

/**
 * Check the amount with the exchange rates of today.
 *
 * The hand-written operation of the jobs test (scripts/jobs_test.py): it
 * does not call the API, and sets the status `paid`, so that the test sees
 * the run.
 */
export async function checkRates(record: Invoice): Promise<void> {
  await invoiceRepository.update(record.id, { status: "paid" });
}
