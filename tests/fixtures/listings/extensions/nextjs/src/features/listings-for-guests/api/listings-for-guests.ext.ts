// Created by appgen once. appgen never changes or deletes this file.
// @trace:manual operations.listings_for_guests file
// The hand-written code of the fixture tests/fixtures/listings.yaml: the
// checks copy it into the app before they generate it.
import "server-only";

import type { Listing, ListingsForGuestsParams } from "@/entities/listing";
import { listingRepository as listings } from "@/entities/listing/server";

/** Return the listings of the city with room for the guests, the cheapest first. */
export async function listingsForGuests(params: ListingsForGuestsParams): Promise<Listing[]> {
  const result = await listings.list({
    filters: [
      { field: "city", op: "eq", value: params.city },
      ...(params.guests === undefined || params.guests === null
        ? []
        : [{ field: "guests" as const, op: "gte" as const, value: params.guests }]),
    ],
    sort: [
      { field: "nightlyRate", direction: "asc" },
      { field: "title", direction: "asc" },
    ],
  });
  return result.items;
}
