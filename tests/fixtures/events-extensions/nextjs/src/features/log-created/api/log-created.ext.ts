// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.log_created file
import "server-only";

import { entryRepository } from "@/entities/entry/server";
import type { Task } from "@/entities/task";
import { taskRepository } from "@/entities/task/server";

/**
 * Write the new task in the log, and give it 1 point.
 *
 * The hand-written operation of the events test (scripts/events_test.py).
 * The change of the points is in the operation of an event, so it starts
 * no event `changed`. For a task whose title starts with FAIL, the
 * operation fails after its writes, so that the test sees the roll back
 * of the create.
 */
export async function logCreated(record: Task): Promise<void> {
  await entryRepository.create({ text: `created ${record.title}` });
  await taskRepository.update(record.id, { points: 1 });
  if (record.title.startsWith("FAIL")) {
    throw new Error(`The test fails the create of ${record.title}.`);
  }
}
