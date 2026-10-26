// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.log_deleted file
import "server-only";

import { entryRepository } from "@/entities/entry/server";
import type { Task } from "@/entities/task";
import { taskRepository } from "@/entities/task/server";

/**
 * Write the deleted task in the log.
 *
 * The hand-written operation of the events test (scripts/events_test.py):
 * it gets the record, which the database does not have any more. For a
 * task whose title starts with KEEP, the operation fails after its write,
 * so that the test sees the roll back of the delete.
 */
export async function logDeleted(record: Task): Promise<void> {
  const stored = await taskRepository.exists(record.id);
  await entryRepository.create({ text: `deleted ${record.title} ${stored ? "stored" : "gone"}` });
  if (record.title.startsWith("KEEP")) {
    throw new Error(`The test fails the delete of ${record.title}.`);
  }
}
