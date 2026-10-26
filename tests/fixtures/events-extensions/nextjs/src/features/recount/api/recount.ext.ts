// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.recount file
import "server-only";

import { entryRepository } from "@/entities/entry/server";
import type { RecountParams, Task } from "@/entities/task";
import { taskRepository } from "@/entities/task/server";

/**
 * Compute the score of the task from its points.
 *
 * The hand-written operation of the events test (scripts/events_test.py):
 * it writes the points in the log, and sets the score. It fails for 13
 * points, after its writes, so that the test sees the roll back of the
 * change.
 */
export async function recount(record: Task, params: RecountParams): Promise<void> {
  await entryRepository.create({ text: `recount ${record.title} ${record.points}` });
  const points = record.points ?? 0;
  await taskRepository.update(record.id, { score: points * (params.factor ?? 2) });
  if (points === 13) {
    throw new Error(`The test fails the score of ${record.title}.`);
  }
}
