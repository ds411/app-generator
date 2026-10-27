"""Tests of the point fields and the filters `near` and `area` (ADR 0046)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings.shared.auth import uses_me
from appgen.bindings.shared.mock_data import mock_data
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.dsl.geo import point_value
from appgen.dsl.schema import json_schema
from appgen.dsl.ui.fields import default_widget, resolve_path
from appgen.dsl.ui.views import AreaFilter, NearFilter, TableView
from appgen.gen import GenerationResult, find_binding, generate
from appgen.gen.render import GenerationError

ROOT = Path(__file__).parent.parent
PLACES = ROOT / "tests" / "fixtures" / "places.yaml"
BASE = dedent(
    """\
    version: 0
    app: { name: sites, title: Sites }
    entities:
      Region:
        fields:
          name: { type: string, required: true }
          center: { type: point }
      Site:
        crud: { operations: [list, create, update], views: [table], forms: [create] }
        display_field: name
        fields:
          name: { type: string, required: true }
          location: { type: point, required: true }
          visits: { type: integer }
        relations:
          region: { kind: many_to_one, target: Region }
    ui:
      views:
        sites:
          kind: table
          entity: Site
          columns: { name: {} }
          filters:
            nearby: { kind: near, field: location, distance: 2.5 }
            in_map: { kind: area, field: location }
            near_region: { kind: near, field: region.center }
    """
)


def files(definition_text: str | None = None, binding: str = "fastapi") -> dict[str, str]:
    """Return the generated files of the places fixture, or of a definition, by path."""
    definition = (
        load_definition(PLACES)
        if definition_text is None
        else load_definition_text(definition_text, "app.yaml")
    )
    result: GenerationResult = generate(definition, find_binding(binding))
    return {f.path: f.content for f in result.files}


def diagnostics(text: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def codes(text: str) -> list[tuple[str, str | None]]:
    return [(code, element) for code, element, _ in diagnostics(text)]


def test_a_point_field_and_the_geo_filters_are_valid() -> None:
    assert codes(BASE) == []
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.entities["Site"].fields["location"].is_point
    view = definition.ui.views["sites"] if definition.ui else None
    assert isinstance(view, TableView)
    nearby, in_map, near_region = view.filters.values()
    assert isinstance(nearby, NearFilter) and nearby.distance == 2.5
    assert isinstance(in_map, AreaFilter)
    assert isinstance(near_region, NearFilter) and near_region.distance == 10
    target = resolve_path(definition, "Site", "location")
    assert default_widget(target) == "point"


def test_the_schema_has_the_point_type_and_the_geo_filters() -> None:
    text = str(json_schema())
    assert "'point'" in text
    assert "NearFilter" in text and "AreaFilter" in text


@pytest.mark.parametrize(
    ("value", "point"),
    [
        ({"lat": 38.7, "lng": -9.1}, {"lat": 38.7, "lng": -9.1}),
        ({"lat": -90, "lng": 180}, {"lat": -90.0, "lng": 180.0}),
        ("38.7223,-9.1393", {"lat": 38.7223, "lng": -9.1393}),
        (" 1 , 2 ", {"lat": 1.0, "lng": 2.0}),
    ],
)
def test_a_point_is_a_mapping_or_a_text(value: object, point: dict[str, float]) -> None:
    assert point_value(value) == point


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ({"lat": 91, "lng": 0}, "latitude 'lat' must be from -90 to 90"),
        ({"lat": 0, "lng": -180.5}, "longitude 'lng' must be from -180 to 180"),
        ({"lat": 0}, "only the keys 'lat' and 'lng'"),
        ({"lat": 0, "lng": 0, "alt": 3}, "only the keys 'lat' and 'lng'"),
        ({"lat": True, "lng": 0}, "a number for the latitude"),
        ("38.7", "a latitude and a longitude"),
        ("a,b", "a latitude and a longitude"),
        (12, "a mapping with 'lat' and 'lng'"),
    ],
)
def test_a_point_out_of_its_range_is_an_error(value: object, problem: str) -> None:
    with pytest.raises(ValueError, match=problem):
        point_value(value)


def test_a_default_and_a_seed_record_take_a_point() -> None:
    text = BASE.replace(
        "center: { type: point }", "center: { type: point, default: { lat: 1, lng: 2 } }"
    ) + dedent(
        """\
        seed:
          Site:
            records:
              tower: { name: Tower, location: "38.69,-9.21" }
              far: { name: Far, location: { lat: 95, lng: 0 } }
        """
    )
    found = diagnostics(text)
    assert [(c, e) for c, e, _ in found] == [("invalid-value", "seed.Site.records.far")]
    assert "the latitude 'lat' must be from -90 to 90" in found[0][2]
    bad_default = BASE.replace("center: { type: point }", "center: { type: point, default: 3 }")
    assert codes(bad_default) == [("invalid-value", "entities.Region.fields.center")]


@pytest.mark.parametrize(
    ("change", "code", "element"),
    [
        (
            (
                "location: { type: point, required: true }",
                "location: { type: point, unique: true }",
            ),
            "invalid-option",
            "entities.Site.fields.location",
        ),
        (
            ("location: { type: point, required: true }", "location: { type: point, min: 0 }"),
            "invalid-option",
            "entities.Site.fields.location",
        ),
        (
            ("visits: { type: integer }", "location_lat: { type: decimal }"),
            "duplicate-name",
            "entities.Site.fields.location",
        ),
        (
            ("{ kind: near, field: location, distance: 2.5 }", "{ kind: near, field: name }"),
            "unsuitable-field",
            "ui.views.sites.filters.nearby",
        ),
        (
            ("{ kind: area, field: location }", "{ kind: area, field: visits }"),
            "unsuitable-field",
            "ui.views.sites.filters.in_map",
        ),
        (
            ("columns: { name: {} }", "columns: { name: {} }\n      sort: { field: location }"),
            "unsuitable-field",
            "ui.views.sites.sort",
        ),
        (
            ("display_field: name", "display_field: location"),
            "unsuitable-field",
            "entities.Site",
        ),
    ],
)
def test_the_validator_reports_a_wrong_use_of_a_point(
    change: tuple[str, str], code: str, element: str
) -> None:
    assert codes(BASE.replace(*change)) == [(code, element)]


def test_a_geo_filter_on_a_field_that_is_not_a_point_says_so() -> None:
    text = BASE.replace(
        "{ kind: near, field: location, distance: 2.5 }", "{ kind: near, field: name }"
    )
    [(_, _, message)] = diagnostics(text)
    assert message == (
        "A near filter does not suit the field 'Site.name' (string). It needs one of: point."
    )


@pytest.mark.parametrize("distance", ["0", "-1", "20039"])
def test_the_distance_of_a_near_filter_is_positive_and_at_most_half_the_earth(
    distance: str,
) -> None:
    text = BASE.replace("distance: 2.5", f"distance: {distance}")
    with pytest.raises(DefinitionError):
        load_definition_text(text, "app.yaml")


def test_a_rule_cannot_use_a_point() -> None:
    text = BASE.replace(
        "    relations:\n      region:",
        "    rules:\n      one_place: { kind: unique, fields: [name, location] }\n    relations:\n"
        "      region:",
    )
    [(code, element, message)] = diagnostics(text)
    assert (code, element) == ("unsuitable-field", "entities.Site.rules.one_place")
    assert message == "A rule cannot use the point field 'location' (type 'point')."


def test_a_notification_and_the_param_of_an_operation_cannot_use_a_point() -> None:
    text = BASE + dedent(
        """\
        notifications:
          moved:
            entity: Site
            event: changed
            fields: [location]
            receivers: [region]
            text: The site is at {location}.
        operations:
          move_site:
            kind: custom
            entity: Site
            params:
              to: { type: point, required: true }
            returns: Site
        """
    )
    found = [(c, e, m) for c, e, m in diagnostics(text) if "auth" not in m]
    assert found == [
        (
            "unsuitable-field",
            "notifications.moved",
            "The field or relation 'location' is the point field 'Site.location'. A notification "
            "uses the stored fields, except the files and the points, and the 'many_to_one' "
            "relations.",
        ),
        (
            "unsuitable-field",
            "notifications.moved",
            "The value in braces 'location' is the point field 'Site.location'. A notification "
            "uses the stored fields, except the files and the points, and the 'many_to_one' "
            "relations.",
        ),
        (
            "invalid-option",
            "operations.move_site.params.to",
            "The type 'point' is only for entity fields.",
        ),
    ]


def test_a_geo_filter_has_no_default_for_the_signed_in_user() -> None:
    text = BASE.replace(
        "entities:\n",
        "auth: { user_entity: User, username_field: email }\nentities:\n"
        "  User:\n    fields:\n      email: { type: email, required: true, unique: true }\n",
    )
    definition = load_definition_text(text, "app.yaml")
    assert validate_definition(definition) == []
    assert not uses_me(definition)


def test_the_mock_records_have_points_near_the_default() -> None:
    text = BASE.replace(
        "center: { type: point }", "center: { type: point, default: { lat: 10, lng: 20 } }"
    )
    data = mock_data(load_definition_text(text, "app.yaml"))
    centers = [r["center"] for r in data["Region"] if r["center"] is not None]
    assert centers
    for center in centers:
        assert abs(center["lat"] - 10) <= 0.05 and abs(center["lng"] - 20) <= 0.08
    for record in data["Site"]:
        assert point_value(record["location"]) == record["location"]


@pytest.mark.parametrize("binding", ["nextjs", "react"])
def test_the_front_ends_stop_for_a_point_field(binding: str) -> None:
    with pytest.raises(GenerationError, match="does not generate 'point' fields yet"):
        files(binding=binding)


@pytest.fixture(scope="module")
def places() -> dict[str, str]:
    return files()


def test_the_fastapi_model_keeps_a_point_in_two_columns_and_an_index(
    places: dict[str, str],
) -> None:
    model = places["app/features/places/models.py"]
    assert 'Index("ix_places_location", "location_lat", "location_lng"),' in model
    assert "location_lat: Mapped[float] = mapped_column(Double)" in model
    assert 'location: Mapped[GeoPoint] = composite("location_lat", "location_lng")' in model
    assert "entrance_lat: Mapped[float | None] = mapped_column(Double)" in model
    migration = places["migrations/versions/0001_schema.py"]
    assert 'sa.Column("location_lat", sa.Double(), nullable=False),' in migration
    assert 'sa.Column("entrance_lng", sa.Double(), nullable=True),' in migration
    assert (
        'op.create_index("ix_places_location", "places", ["location_lat", "location_lng"])'
        in migration
    )
    schemas = places["app/features/places/schemas.py"]
    assert "entrance: GeoPoint | None = GeoPoint(lat=38.7139, lng=-9.1335)" in schemas
    types = places["app/core/types.py"]
    assert "class GeoPoint:" in types and "Field(ge=-90, le=90" in types


def test_the_fastapi_list_endpoint_takes_the_geo_parameters(places: dict[str, str]) -> None:
    code = places["app/features/places/list_places.py"]
    assert "location_near: PointText | None = Field(" in code
    assert "location_distance: float = Field(" in code
    assert "default=5.0," in code and "gt=0," in code
    assert "location_area: BoxText | None = Field(" in code
    assert 'alias="city.center_near"' in code
    assert "near(\n                Place.location_lat," in code
    assert "in_area(Place.location_lat, Place.location_lng, query.location_area)" in code
    assert "City.center_lat" in code and "Place.city.has(" in code
    db = places["app/core/db.py"]
    assert 'event.listen(engine.sync_engine, "connect", add_math_functions)' in db


def test_the_fastapi_seed_and_the_change_log_have_the_points(places: dict[str, str]) -> None:
    seed = places["app/core/seed_data.py"]
    assert '"location_lat": 38.6916,' in seed and '"center_lng": -8.6291,' in seed
    history = places["app/core/history.py"]
    assert 'return {"lat": value.lat, "lng": value.lng}' in history
    repository = places["app/features/places/repository.py"]
    assert 'values["location"] = GeoPoint(**point)' in repository


def test_the_fastapi_app_without_a_near_filter_has_no_math_functions() -> None:
    text = "".join(line for line in BASE.splitlines(keepends=True) if "kind: near" not in line)
    generated = files(text)
    assert "add_math_functions" not in generated["app/core/db.py"]
    geo = generated["app/core/geo.py"]
    assert "def in_area(" in geo and "add_math_functions" not in geo
