// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.sync_calendar file
import "server-only";

import type { Calendar } from "@/entities/calendar";
import { calendarRepository } from "@/entities/calendar/server";
import { calendarClient } from "@/shared/api/calendar";

/**
 * Count the events of the calendar of the user.
 *
 * The hand-written code of the fixture tests/fixtures/api-connections.yaml:
 * it counts the events of the signed-in user, or of the user of the run of
 * the job. The checks copy it into the app before they generate it.
 */
export async function syncCalendar(record: Calendar): Promise<void> {
  const events = await calendarClient().listEvents({ limit: 100 });
  await calendarRepository.update(record.id, { events: events.items.length });
}
