"""Places on the earth: the field type `point`, and the list filters `near` and `area`.

A point field holds a latitude and a longitude in degrees (WGS 84), for
example the place of a listing (ADR 0046). The value is a mapping
`{lat: 38.7223, lng: -9.1393}`. The latitude is from -90 to 90, and the
longitude from -180 to 180. The apps keep a point in two columns of
numbers, `<field>_lat` and `<field>_lng`, with an index of the two
columns. They do not need PostGIS, so that the tests run on SQLite.

The filter `near` keeps the records whose point is at most a distance
from a point, and the filter `area` keeps the records whose point is
in a box of a map.
"""

import math
from collections.abc import Mapping
from typing import cast

POINT_COLUMNS = ("lat", "lng")
"""The suffixes of the two columns of a point field: `<field>_lat` and `<field>_lng`."""
LAT_RANGE = (-90.0, 90.0)
"""The smallest and the largest latitude, in degrees."""
LNG_RANGE = (-180.0, 180.0)
"""The smallest and the largest longitude, in degrees."""
DEFAULT_DISTANCE = 10.0
"""The distance of a `near` filter without `distance`, in kilometers."""
MAX_DISTANCE = 20_038.0
"""The largest distance of a `near` filter: half of the circumference of the earth, in km."""


def point_value(value: object) -> dict[str, float]:
    """Return a point as `{"lat": ..., "lng": ...}`. Raise ValueError if it is not a point.

    The value is a mapping with the keys `lat` and `lng`, or a text
    `<lat>,<lng>`, for example `38.7223,-9.1393` (a cell of a CSV file).
    """
    if isinstance(value, str):
        parts = value.split(",")
        if len(parts) != 2:
            raise ValueError("expected a latitude and a longitude, for example '38.72,-9.14'")
        try:
            value = {"lat": float(parts[0]), "lng": float(parts[1])}
        except ValueError:
            raise ValueError(
                "expected a latitude and a longitude, for example '38.72,-9.14'"
            ) from None
    if not isinstance(value, Mapping):
        raise ValueError(
            "expected a mapping with 'lat' and 'lng', for example {lat: 38.72, lng: -9.14}"
        )
    mapping = cast(Mapping[object, object], value)
    keys = set(mapping)
    if keys != {"lat", "lng"}:
        raise ValueError("expected a mapping with only the keys 'lat' and 'lng'")
    point: dict[str, float] = {}
    for key, (low, high), what in (("lat", LAT_RANGE, "latitude"), ("lng", LNG_RANGE, "longitude")):
        number = mapping[key]
        if isinstance(number, bool) or not isinstance(number, int | float):
            raise ValueError(f"expected a number for the {what} '{key}'")
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"the {what} '{key}' must be from {low:g} to {high:g}")
        point[key] = float(number)
    return point


def point_columns(name: str) -> tuple[str, str]:
    """Return the names of the columns of a point field, for example `place_lat`, `place_lng`."""
    lat, lng = POINT_COLUMNS
    return f"{name}_{lat}", f"{name}_{lng}"
