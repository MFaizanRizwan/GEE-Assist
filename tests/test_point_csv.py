"""Sample points from CSV tables, for IDW."""

import pytest

from backend.business.interpolation.point_table import guess_coordinate_columns, inspect_csv, read_point_csv
from backend.exceptions import InterpolationError


def _csv(tmp_path, text, name="points.csv", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return str(path)


def test_points_come_with_every_column_and_the_numeric_ones_typed(tmp_path):
    path = _csv(tmp_path, "station,lon,lat,rain_mm\nA,73.05,31.40,12.5\nB,73.10,31.45,20\nC,73.20,31.50,\n")
    layer = read_point_csv(path)
    assert layer.kind == "point" and layer.feature_count == 3
    assert [(f.name, f.type) for f in layer.fields] == [("station", "text"), ("lon", "number"), ("lat", "number"),
                                                        ("rain_mm", "number")]
    first = layer.features[0]
    assert first.parts == (((73.05, 31.40),),) and first.attributes == {"station": "A", "lon": 73.05,
                                                                       "lat": 31.40, "rain_mm": 12.5}
    assert layer.features[2].attributes["rain_mm"] is None          # an empty cell
    assert layer.bounds == pytest.approx((73.05, 31.40, 73.20, 31.50))


@pytest.mark.parametrize("names,expected", [
    (["Longitude", "Latitude", "v"], ("Longitude", "Latitude")),
    (["LNG", "LAT", "v"], ("LNG", "LAT")),
    (["x", "y", "v"], ("x", "y")),
    (["Lon (deg)", "Lat (deg)", "v"], ("Lon (deg)", "Lat (deg)")),
    (["longitude_wgs84", "latitude_wgs84", "v"], ("longitude_wgs84", "latitude_wgs84")),
    (["east", "north", "v"], ("", "")),
])
def test_coordinate_columns_are_found_by_name(names, expected):
    assert guess_coordinate_columns(names) == expected


def test_semicolons_tabs_and_a_byte_order_mark_are_read(tmp_path):
    semi = _csv(tmp_path, "\ufeffLatitude;Longitude;temp\n31.4;73.0;20\n31.5;73.1;22\n", "semi.csv")
    layer = read_point_csv(semi)
    assert layer.features[0].parts == (((73.0, 31.4),),) and layer.fields[0].name == "Latitude"
    tabs = _csv(tmp_path, "lon\tlat\tz\n73\t31\t1\n74\t32\t2\n", "tabs.csv")
    assert read_point_csv(tabs).feature_count == 2
    latin = _csv(tmp_path, "lon,lat,name,v\n73,31,Muzaffargarh é,1\n74,32,b,2\n", "latin.csv", "cp1252")
    assert read_point_csv(latin).features[0].attributes["name"] == "Muzaffargarh é"


def test_rows_without_coordinates_are_skipped(tmp_path):
    path = _csv(tmp_path, "lon,lat,v\n73,31,1\n,31,2\nabc,31,3\n74,32,4\n")
    assert read_point_csv(path).feature_count == 2


def test_columns_can_be_chosen_when_their_names_say_nothing(tmp_path):
    path = _csv(tmp_path, "E,N,v\n73,31,1\n74,32,2\n")
    table = inspect_csv(path)
    assert table.numeric == ("E", "N", "v") and (table.lon_column, table.lat_column) == ("", "")
    with pytest.raises(InterpolationError, match="Choose the CSV's longitude and latitude"):
        read_point_csv(path)
    assert read_point_csv(path, "E", "N").feature_count == 2


def test_projected_metres_are_refused_with_a_reason(tmp_path):
    path = _csv(tmp_path, "x,y,v\n500000,3500000,1\n510000,3510000,2\n")
    with pytest.raises(InterpolationError, match="not longitude / latitude in degrees"):
        read_point_csv(path)


def test_a_table_too_small_to_interpolate_is_refused(tmp_path):
    with pytest.raises(InterpolationError, match="longitude, a latitude and a value"):
        read_point_csv(_csv(tmp_path, "lon,lat\n73,31\n"))
    with pytest.raises(InterpolationError, match="no rows"):
        read_point_csv(_csv(tmp_path, "lon,lat,v\n", "empty.csv"))
