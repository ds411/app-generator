// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.file_issue file
import "server-only";

import type { Ticket } from "@/entities/ticket";
import { ticketRepository } from "@/entities/ticket/server";
import { jiraClient } from "@/shared/api/jira";

/**
 * Make an issue in Jira for the ticket, and keep its key, or add a comment to its issue.
 *
 * The hand-written code of the fixture tests/fixtures/jira-accounts.yaml:
 * it makes an issue in Jira for a ticket without one, or adds a comment to
 * the issue of the ticket, in the name of the signed-in user, or of the
 * user of the run of the job. The checks copy it into the app before they
 * generate it.
 */
export async function fileIssue(record: Ticket): Promise<void> {
  if (record.issueKey) {
    const text = { type: "text", text: `The ticket is still open: ${record.title}` };
    const body = { type: "doc", version: 1, content: [{ type: "paragraph", content: [text] }] };
    await jiraClient().addComment({ issueIdOrKey: record.issueKey }, { body });
    return;
  }
  const fields = { project: { key: "SUP" }, issuetype: { name: "Task" }, summary: record.title };
  const issue = await jiraClient().createIssue({}, { fields });
  await ticketRepository.update(record.id, { issueKey: issue.key ?? null });
}
