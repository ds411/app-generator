// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual webhooks.commits file
import "server-only";

import { commentRepository } from "@/entities/comment/server";
import { personRepository } from "@/entities/person/server";
import { taskRepository } from "@/entities/task/server";
import { t } from "@/shared/lib/i18n";
import { WebhookError } from "@/shared/webhooks";

import type { CommitEvent } from "../model/event";

/**
 * The code host reports a commit that refers to a task. The app adds the
 * commit message to the task as a comment of the author.
 *
 * An unknown task gives 404, and an unknown author 422: the code host can
 * then deliver the event again later. This file is the hand-written code
 * of the project tracker example: the checks copy it into the app before
 * they generate it (examples/README.md).
 */
export async function handleCommits(event: CommitEvent, _headers: Headers): Promise<void> {
  const task = await taskRepository.get(event.task_id);
  const people = await personRepository.list({
    filters: [{ field: "email", op: "eq", value: event.author_email }],
    page: 1,
    pageSize: 1,
  });
  const [author] = people.items;
  if (author === undefined) {
    throw new WebhookError(422, t("No person has the email address {email}.", { email: event.author_email }));
  }
  const body = event.url === undefined ? event.message : `${event.message}\n\n${event.url}`;
  await commentRepository.create({
    body: body.slice(0, 10000),
    postedAt: new Date().toISOString(),
    taskId: task.id,
    authorId: author.id,
  });
}
