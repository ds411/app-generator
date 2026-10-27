// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.bookings_by_month file
// The hand-written code of the fixture tests/fixtures/listings.yaml: the
// checks copy it into the app before they generate it.
import "server-only";

import type { BookingsByMonthParams, BookingsByMonthRow } from "@/entities/booking";
import { bookingRepository as bookings } from "@/entities/booking/server";

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Return one row for each month of the year with a check-in, in the order of
 * the months. The nights of a booking count in the month of its check-in.
 */
export async function bookingsByMonth(params: BookingsByMonthParams): Promise<BookingsByMonthRow[]> {
  const year = String(params.year);
  const months = new Map<string, BookingsByMonthRow>();
  for (const booking of (await bookings.list()).items) {
    if (!booking.checkIn.startsWith(`${year}-`)) continue;
    const month = `${booking.checkIn.slice(0, 7)}-01`;
    const row = months.get(month) ?? { month, bookings: 0, nights: 0 };
    row.bookings += 1;
    row.nights += Math.round((Date.parse(booking.checkOut) - Date.parse(booking.checkIn)) / DAY_MS);
    months.set(month, row);
  }
  return [...months.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, row]) => row);
}
