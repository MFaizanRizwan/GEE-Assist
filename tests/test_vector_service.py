"""The vector service: reading ESRI shapefiles and reprojecting them to WGS84."""

import pytest

shapefile = pytest.importorskip("shapefile")  # pyshp

from backend.business.vector import VectorService  # noqa: E402
from backend.dto.vector_dto import POINT, POLYGON, POLYLINE  # noqa: E402
from backend.exceptions import VectorError  # noqa: E402

# A minimal WGS84 / Pseudo-Mercator (EPSG:3857) .prj, so reprojection to lon/lat is exercised.
MERCATOR_PRJ = (
    'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,'
    '298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1],AUTHORITY["EPSG","3857"]]'
)
WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
)


def write_polygons(path, prj=WGS84_PRJ):
    w = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    w.field("name", "C")
    w.field("pop", "N")
    w.poly([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]])
    w.record("Alpha", 100)
    w.poly([[[3, 3], [5, 3], [5, 5], [3, 5], [3, 3]]])
    w.record("Beta", 50)
    w.close()
    if prj:
        path.with_suffix(".prj").write_text(prj)
    return path


def test_reads_polygons_with_attributes(tmp_path):
    layer = VectorService().load_shapefile(str(write_polygons(tmp_path / "areas.shp")))
    assert layer.kind == POLYGON
    assert layer.feature_count == 2
    assert layer.name == "areas"
    assert [(f.name, f.type) for f in layer.fields] == [("name", "text"), ("pop", "number")]
    assert layer.features[0].attributes == {"name": "Alpha", "pop": 100}
    assert layer.crs == "EPSG:4326"
    assert layer.bounds == pytest.approx((0.0, 0.0, 5.0, 5.0))


def test_reprojects_metres_to_degrees(tmp_path):
    """A square drawn in EPSG:3857 metres near the equator becomes a small box in degrees."""
    p = tmp_path / "merc.shp"
    w = shapefile.Writer(str(p), shapeType=shapefile.POLYGON)
    w.field("id", "N")
    w.poly([[[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]]])
    w.record(1)
    w.close()
    p.with_suffix(".prj").write_text(MERCATOR_PRJ)

    layer = VectorService().load_shapefile(str(p))
    assert layer.crs == "EPSG:3857"
    minx, miny, maxx, maxy = layer.bounds
    assert minx == pytest.approx(0.0, abs=1e-6)
    assert maxx == pytest.approx(0.008983, abs=1e-5)  # 1000 m ≈ 0.009° of longitude at the equator
    assert maxy == pytest.approx(0.009043, abs=1e-4)


def test_reads_points_and_lines(tmp_path):
    pts = tmp_path / "pts.shp"
    w = shapefile.Writer(str(pts), shapeType=shapefile.POINT)
    w.field("label", "C")
    w.point(10, 20)
    w.record("A")
    w.point(11, 21)
    w.record("B")
    w.close()
    point_layer = VectorService().load_shapefile(str(pts))
    assert point_layer.kind == POINT and point_layer.feature_count == 2
    assert point_layer.features[0].parts[0][0] == pytest.approx((10.0, 20.0))

    lines = tmp_path / "lines.shp"
    w = shapefile.Writer(str(lines), shapeType=shapefile.POLYLINE)
    w.field("road", "C")
    w.line([[[0, 0], [1, 1], [2, 0]]])
    w.record("Main")
    w.close()
    line_layer = VectorService().load_shapefile(str(lines))
    assert line_layer.kind == POLYLINE and line_layer.features[0].parts[0][0] == pytest.approx((0.0, 0.0))


def test_polygon_with_a_hole_keeps_both_rings(tmp_path):
    p = tmp_path / "donut.shp"
    w = shapefile.Writer(str(p), shapeType=shapefile.POLYGON)
    w.field("id", "N")
    # Outer ring clockwise, inner ring (hole) counter-clockwise, as ESRI expects.
    w.poly([[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
            [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]])
    w.record(1)
    w.close()
    layer = VectorService().load_shapefile(str(p))
    assert len(layer.features[0].parts) == 2  # outer boundary + hole


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(VectorError, match="not there"):
        VectorService().load_shapefile(str(tmp_path / "nope.shp"))


def test_non_shp_is_rejected(tmp_path):
    other = tmp_path / "data.tif"
    other.write_bytes(b"not a shapefile")
    with pytest.raises(VectorError, match="shapefile"):
        VectorService().load_shapefile(str(other))


def test_no_prj_is_assumed_wgs84(tmp_path):
    layer = VectorService().load_shapefile(str(write_polygons(tmp_path / "areas.shp", prj="")))
    assert "assumed WGS84" in layer.crs
    assert layer.bounds == pytest.approx((0.0, 0.0, 5.0, 5.0))
