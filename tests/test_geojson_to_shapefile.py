"""Writing a GeoJSON FeatureCollection to a shapefile (Earth Engine results)."""

import pytest

pytest.importorskip("shapefile")

from backend.business.catalog.geojson_to_shapefile import write_geojson  # noqa: E402
from backend.business.vector import VectorService  # noqa: E402
from backend.dto.vector_dto import POINT, POLYGON  # noqa: E402
from backend.exceptions import CatalogError  # noqa: E402


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def test_polygons_round_trip_through_the_vector_reader(tmp_path):
    fc = _fc([
        {"type": "Feature", "properties": {"ADM1_NAME": "Punjab", "pop": 110000000},
         "geometry": {"type": "Polygon", "coordinates": [[[71, 30], [75, 30], [75, 33], [71, 33], [71, 30]]]}},
        {"type": "Feature", "properties": {"ADM1_NAME": "Sindh", "pop": 48000000},
         "geometry": {"type": "Polygon", "coordinates": [[[66, 24], [71, 24], [71, 28], [66, 28], [66, 24]]]}},
    ])
    written = write_geojson(fc, str(tmp_path / "prov.shp"))
    assert sorted(p.rsplit(".", 1)[1] for p in written) == ["dbf", "prj", "shp", "shx"]

    layer = VectorService().load_shapefile(str(tmp_path / "prov.shp"))
    assert layer.kind == POLYGON and layer.feature_count == 2
    assert [f.name for f in layer.fields] == ["ADM1_NAME", "pop"]
    assert layer.features[0].attributes["ADM1_NAME"] == "Punjab"
    assert layer.crs == "EPSG:4326"


def test_points_round_trip(tmp_path):
    fc = _fc([{"type": "Feature", "properties": {"city": "Lahore"},
               "geometry": {"type": "Point", "coordinates": [74.3, 31.5]}}])
    write_geojson(fc, str(tmp_path / "cities.shp"))
    layer = VectorService().load_shapefile(str(tmp_path / "cities.shp"))
    assert layer.kind == POINT
    assert layer.features[0].parts[0][0] == pytest.approx((74.3, 31.5))


def test_long_field_names_are_truncated_and_unique(tmp_path):
    fc = _fc([{"type": "Feature",
               "properties": {"administrative_name": "A", "administrative_code": 1},
               "geometry": {"type": "Point", "coordinates": [0, 0]}}])
    write_geojson(fc, str(tmp_path / "x.shp"))
    layer = VectorService().load_shapefile(str(tmp_path / "x.shp"))
    names = [f.name for f in layer.fields]
    assert all(len(n) <= 10 for n in names)
    assert len(names) == len(set(names))  # de-duplicated


def test_mixed_geometry_keeps_the_first_type(tmp_path):
    fc = _fc([
        {"type": "Feature", "properties": {"n": 1},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
        {"type": "Feature", "properties": {"n": 2}, "geometry": {"type": "Point", "coordinates": [5, 5]}},
    ])
    write_geojson(fc, str(tmp_path / "m.shp"))
    layer = VectorService().load_shapefile(str(tmp_path / "m.shp"))
    assert layer.kind == POLYGON and layer.feature_count == 1  # the point was skipped


def test_empty_collection_is_rejected(tmp_path):
    with pytest.raises(CatalogError, match="no features"):
        write_geojson(_fc([]), str(tmp_path / "empty.shp"))
