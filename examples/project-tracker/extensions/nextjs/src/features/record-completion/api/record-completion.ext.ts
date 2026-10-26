// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.record_completion file
import "server-only";

import type { Task } from "@/entities/task";
import { taskRepository } from "@/entities/task/server";

/**
 * Set the completion time of a task that is done, and clear it for other tasks.
 *
 * The event `changed` of Task runs the operation after a change of the
 * status, in the transaction of the change (ADR 0031). This file is the
 * hand-written code of the project tracker example: the checks copy it
 * into the app before they generate it (examples/README.md).
 */
export async function recordCompletion(record: Task): Promise<void> {
  if (record.status !== "done") {
    await taskRepository.update(record.id, { completedAt: null });
  } else if (record.completedAt === null) {
    await taskRepository.update(record.id, { completedAt: new Date().toISOString() });
  }
}
