# 0046. Places: point fields and the geo filters

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

No field type holds a place. Real apps find the listings near a place,
the stores in the visible part of a map, and the drivers near a pickup.
The report "appgen Real App Coverage" lists these features for 12
well-known web apps.

The options for the storage of a place:

- **PostGIS.** It has the types, the indexes, and the functions of
  geography, but SQLite does not have it, and the generated tests of
  the FastAPI app run on SQLite and on Postgres. Each app also needs the
  extension in its database.
- **One JSON column.** The database cannot index the latitude, so each
  filter reads all rows.
- **Two columns of numbers and an index.** Each database has them. A
  range of latitudes uses the index, and the exact distance needs only
  `sin` and `cos`.

## Decision

The field type `point` holds a latitude and a longitude in degrees
(WGS 84). The value is a mapping `{lat, lng}`, with the latitude from
-90 to 90 and the longitude from -180 to 180. A point field takes
`required`, `label`, `description`, and a `default` point. It takes no
`unique`, and it cannot be computed. An entity rule, a sort, and the
filter of a widget or of a job cannot use it, because a place has no
order. A point is not a text, so it cannot be the display field, a
value of a notification, or a field of the sign-up form. Only an entity
field can be a point: the param of an operation cannot.

The apps keep a point in two columns of numbers, `<field>_lat` and
`<field>_lng`, with an index of the two columns, latitude first. No
other member of the entity can have the name of one of the columns.

The list views take two new filters of a point field:

- `near` keeps the records whose point is at most a distance from a
  point. `distance` gives the distance in kilometers until the user
  picks another one (default 10).
- `area` keeps the records whose point is in a box, for example the
  visible part of a map. A box whose west is greater than its east
  crosses the antimeridian.

In the FastAPI app:

- The model has an attribute for each column and a composite attribute
  `GeoPoint` of the two (`app/core/types.py`). The schemas give a point
  as an object `{lat, lng}`, and give 422 for a value out of its range.
- The list endpoint takes `<path>_near` (`<lat>,<lng>`) and
  `<path>_distance` for `near`, and `<path>_area`
  (`<south>,<west>,<north>,<east>`) for `area`. `app/core/geo.py` has
  the conditions. `near` limits the latitudes (and the longitudes, when
  the circle has no pole and does not cross the antimeridian), so that
  the database uses the index, and keeps the points whose haversine
  distance on a sphere of the mean radius of the earth is in the limit.
- SQLite gets the functions `sin` and `cos` on each connection, because
  some builds of SQLite do not have them.
- The change log keeps a point as an object `{lat, lng}`.

### The front ends and the map view

The React and Next.js apps have a point as `GeoPoint` (`{ lat, lng }`)
of `@/shared/api`, with a zod schema of the ranges. A view shows a point
as its latitude and its longitude, and the form widget `point` has an
input for each. The Next.js app keeps a point in one `jsonb` column: its
views read all records and filter them in the browser, so the column
needs no index. The FastAPI app keeps the two columns and the index,
because its list endpoint filters the records.

A view of `kind: map` shows a marker for each record with a point, and
the list of the records in the visible area of the map. `point` is the
point field, `label` the text of a record, and `link` the page that a
record opens. A map takes the filters of a table, except `area`: a move
of the map gives the area. The front ends filter the points in the
browser (`src/shared/lib/geo.ts`, with the haversine formula of the
FastAPI app), and the React app with the FastAPI app sends the filters
and `<point>_area` to the list endpoint.

The options for the map:

- **Leaflet.** A small library of maps with raster tiles, without a
  key, and with the keyboard support of the markers and of the map.
- **MapLibre GL.** Vector tiles, but a larger bundle, WebGL, and a
  style for each tile provider.
- **A map of a provider (Google Maps, Mapbox).** It needs a key and an
  account.

The front ends use Leaflet 1.9. The map loads Leaflet in the browser
after its first render, so that the server render of the Next.js app
does not need the browser. The markers are HTML (`divIcon`), with the
colors of the theme, and need no images of Leaflet. The tile URL is a
build setting: `NEXT_PUBLIC_MAP_TILES` or `VITE_MAP_TILES`, with
`{z}`, `{x}`, and `{y}`, and the attribution `NEXT_PUBLIC_MAP_ATTRIBUTION`
or `VITE_MAP_ATTRIBUTION`. The default is the standard tiles of
OpenStreetMap, with their attribution. The UI tests use a local tile
server (`scripts/places_ui_test.py`), so that they need no network.

An `area` filter of a table or a card list shows the same map in a
popover: the user moves the map, and uses its visible area.

## Consequences

- A FastAPI app finds the records near a place and in a box, on
  Postgres and on SQLite, without an extension of the database.
- The distance is on a sphere: it differs from the distance on the
  ellipsoid of the earth by up to 0.5 percent. The filters of a list are
  not for surveys.
- `near` does not sort the records by their distance. The sort of the
  view applies.
- A point field is a `field`. The element kinds `near_filter` and
  `area_filter` and the form widget `point` are new. The FastAPI binding
  traces the filters in its list endpoints and their tests.
- The element kind `map_view` is new. The apps with a map view or an
  `area` filter get the packages `leaflet` and `@types/leaflet`.
- The standard tiles of OpenStreetMap have a usage policy: a production
  app sets the tile URL of a tile server of its own or of a provider.
- A map of the FastAPI app loads all records before its first move, to
  show all markers. After each move, it loads the records of the
  visible area only.
