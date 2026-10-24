// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.schedule_task file
import "server-only";

import type { Task, ScheduleTaskParams } from "@/entities/task";
import { taskRepository } from "@/entities/task/server";
import { holidaysClient } from "@/shared/api/holidays";

/**
 * Set the due date of the task to a number of working days from today. Weekends and the public holidays of the country are not working days.
 *
 * The function gets the public holidays of each year that it counts from
 * the API. A holiday counts only if it is in all regions. This file is
 * the hand-written code of the project tracker example: the checks copy
 * it into the app before they generate it (examples/README.md).
 */
export async function scheduleTask(record: Task, params: ScheduleTaskParams): Promise<Task> {
  const client = holidaysClient();
  const holidaysByYear = new Map<number, Set<string>>();
  const day = new Date();
  day.setUTCHours(0, 0, 0, 0);
  let left = params.workingDays;
  while (left > 0) {
    day.setUTCDate(day.getUTCDate() + 1);
    const year = day.getUTCFullYear();
    let holidays = holidaysByYear.get(year);
    if (holidays === undefined) {
      const found = await client.getPublicHolidays({ year, countryCode: params.countryCode });
      holidays = new Set(found.filter((holiday) => holiday.global).map((holiday) => holiday.date));
      holidaysByYear.set(year, holidays);
    }
    const weekday = day.getUTCDay();
    if (weekday !== 0 && weekday !== 6 && !holidays.has(day.toISOString().slice(0, 10))) {
      left -= 1;
    }
  }
  return taskRepository.update(record.id, { dueDate: day.toISOString().slice(0, 10) });
}
