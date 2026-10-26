// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual jobs.monthly_close file
import "server-only";

import { customerRepository } from "@/entities/customer/server";

/**
 * The logic of the job `monthly_close`, for a time of its schedule
 * `0 0 1 * *` (UTC).
 *
 * The hand-written logic of the jobs test (scripts/jobs_test.py): it adds
 * a customer with the time in its name, so that the test sees each run.
 */
export async function monthlyClose(time: Date): Promise<void> {
  await customerRepository.create({ name: `Close ${time.toISOString()}` });
}
