// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.log_finished file
import "server-only";

import { entryRepository } from "@/entities/entry/server";
import type { Task } from "@/entities/task";

/**
 * Write the finished task in the log.
 *
 * The hand-written operation of the events test (scripts/events_test.py).
 * For a task whose title starts with STUCK, the operation fails after its
 * write, so that the test sees the roll back of the transition.
 */
export async function logFinished(record: Task): Promise<void> {
  await entryRepository.create({ text: `finished ${record.title} ${record.status}` });
  if (record.title.startsWith("STUCK")) {
    throw new Error(`The test fails the transition of ${record.title}.`);
  }
}
