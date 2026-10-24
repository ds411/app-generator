// The hand-written server action of the widget holidays: it calls the
// holidays API on the server. This file is the hand-written code of the
// project tracker example (examples/README.md).
"use server";

// @trace:manual apis.holidays.operations.getNextPublicHolidays
import { holidaysClient, type PublicHoliday } from "@/shared/api/holidays";

/** The country of the public holidays of the dashboard. */
const COUNTRY_CODE = "DE";

/** Return the public holidays of the next 365 days that are in all regions of the country. */
export async function nextHolidays(): Promise<PublicHoliday[]> {
  const holidays = await holidaysClient().getNextPublicHolidays({ countryCode: COUNTRY_CODE });
  return holidays.filter((holiday) => holiday.global);
}
