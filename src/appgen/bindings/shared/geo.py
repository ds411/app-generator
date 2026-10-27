"""The `point` fields of the entities in the front ends (ADR 0046).

A record has a point as `GeoPoint` (`{ lat, lng }` in degrees), from
`@/shared/api`. The views filter the points in the browser, or send the
geo parameters to the list endpoint of the FastAPI app.
"""

from appgen.dsl.model import AppDefinition

DEFAULT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
"""The tiles of a map without a setting: the standard tiles of OpenStreetMap."""
DEFAULT_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)
"""The attribution of the default tiles, as the tile usage policy of OpenStreetMap asks."""


def has_points(definition: AppDefinition) -> bool:
    """Return True if an entity has a `point` field."""
    return any(
        field.is_point
        for entity in definition.entities.values()
        for field in entity.fields.values()
    )
