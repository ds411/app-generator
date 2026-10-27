// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.bookings_of_listing file
// The hand-written code of the fixture tests/fixtures/listings.yaml: the
// checks copy it into the app before they generate it.
import type { Booking, BookingsOfListingParams } from "@/entities/booking";
import { bookingApi as bookings } from "@/entities/booking";

/** Return the bookings of the listing, by check-in. */
export async function bookingsOfListing(params: BookingsOfListingParams): Promise<Booking[]> {
  const result = await bookings.list({
    filters: [{ field: "listingId", op: "eq", value: params.listing }],
    sort: [
      { field: "checkIn", direction: "asc" },
      { field: "guest", direction: "asc" },
    ],
  });
  return result.items;
}
