"""The terrain service: reading a DEM and deriving hillshade, slope, aspect and contours."""

import math

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from backend.business.terrain import TerrainService  # noqa: E402
from backend.business.terrain.terrain_service import (  # noqa: E402
    aspect_classes,
    contour_segments,
    hillshade,
    slope_degrees,
)
from backend.exceptions import TerrainError  # noqa: E402


def write_dem(path, elevation, cell=30.0, crs="EPSG:32643", nodata=-9999.0, origin=(300000, 3500000)):
    """Write a single-band DEM GeoTIFF (projected metres by default) and return its path."""
    elevation = np.asarray(elevation, dtype="float32")
    h, w = elevation.shape
    transform = from_origin(origin[0], origin[1], cell, cell)
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32",
                       crs=crs, transform=transform, nodata=nodata) as dst:
        dst.write(elevation, 1)
    return path


def east_ramp(n=40, step=10.0):
    """A tilted plane rising to the east by ``step`` metres per column."""
    return np.tile(np.arange(n) * step, (n, 1))


def test_describes_a_dem(tmp_path):
    info = TerrainService().describe(str(write_dem(tmp_path / "dem.tif", east_ramp())))
    assert not info.is_geographic
    assert info.cell_size == (30.0, 30.0)
    assert info.min_elevation == 0.0 and info.max_elevation == pytest.approx(390.0)
    assert info.width == 40 and info.height == 40


def test_slope_of_a_known_plane(tmp_path):
    # Rising 10 m per 30 m cell -> slope = atan(10/30).
    slope = slope_degrees(east_ramp().astype("float64"), (30.0, 30.0))
    assert float(slope[20, 20]) == pytest.approx(math.degrees(math.atan(10 / 30)), abs=1e-6)


def test_aspect_of_an_east_rising_plane_faces_west(tmp_path):
    # A surface rising to the east slopes downhill to the west, so it faces West (class 7).
    aspect = aspect_classes(east_ramp().astype("float64"), (30.0, 30.0))
    assert int(aspect[20, 20]) == 7


def test_hillshade_is_in_range_and_flat_is_uniform():
    flat = np.full((10, 10), 100.0)
    shade = hillshade(flat, (30.0, 30.0))
    assert shade.min() >= 0 and shade.max() <= 255
    assert np.allclose(shade, shade[0, 0])  # a flat surface shades evenly


def test_contours_of_a_ramp_are_straight_lines():
    ramp = east_ramp(n=30, step=10.0).astype("float64")
    segments = contour_segments(ramp, 205.0)  # between column 20 (200 m) and 21 (210 m)
    xs = {round(x0, 2) for x0, _, _, _ in segments}
    assert xs == {20.5}  # one vertical contour, interpolated halfway
    assert len(segments) == 29  # one segment per row of cells


def test_render_each_product(tmp_path):
    svc = TerrainService()
    info = svc.describe(str(write_dem(tmp_path / "dem.tif", east_ramp())))
    for product in ("elevation", "hillshade", "slope", "aspect", "contours"):
        drawn = svc.render(info, product)
        assert drawn.rgba.shape[2] == 4
        assert drawn.width == 40 and drawn.height == 40
        assert drawn.key == product
    # The shaded surfaces carry their own values; contours are a picture only.
    assert svc.render(info, "slope").values is not None
    assert svc.render(info, "contours").values is None


def test_save_product_writes_a_geotiff(tmp_path):
    svc = TerrainService()
    info = svc.describe(str(write_dem(tmp_path / "dem.tif", east_ramp())))
    out = svc.save_product(info, "slope", str(tmp_path / "slope.tif"))
    with rasterio.open(out) as src:
        assert src.count == 1 and src.width == 40 and src.height == 40
        assert float(src.read(1)[20, 20]) == pytest.approx(math.degrees(math.atan(10 / 30)), abs=1e-4)


def test_missing_dem_is_reported(tmp_path):
    with pytest.raises(TerrainError, match="not there"):
        TerrainService().describe(str(tmp_path / "nope.tif"))


def test_geographic_dem_converts_cells_to_metres(tmp_path):
    # A 0.01° cell at ~31°N is ~1 km; slope should be far gentler than the same ramp in metres.
    dem = write_dem(tmp_path / "geo.tif", east_ramp(), cell=0.01, crs="EPSG:4326", origin=(73.0, 31.4))
    info = TerrainService().describe(str(dem))
    assert info.is_geographic
    drawn = TerrainService().render(info, "slope")
    peak = float(np.nanmax(drawn.values))
    assert peak < 1.0  # 10 m over ~1.1 km is well under a degree of slope
