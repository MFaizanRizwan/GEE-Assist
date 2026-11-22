"""The interpolation service: inverse distance weighting of scattered points."""

import numpy as np
import pytest

from backend.business.interpolation import InterpolationService
from backend.business.interpolation.interpolation_service import _estimate_row, _grid
from backend.dto.interpolation_dto import IDWParamsDTO, SamplePointDTO
from backend.exceptions import InterpolationError


def test_estimate_row_exact_equidistant_and_weighted():
    values = np.array([0.0, 10.0])
    dist = np.array([[0.0, 1.0],     # sitting on point 0 -> its value
                     [0.5, 0.5],     # equidistant -> average
                     [0.25, 0.75]])  # nearer point 0 (power 2) -> close to 0
    out = _estimate_row(dist, values, power=2.0, neighbours=0, radius=0.0)
    assert out[0] == 0.0
    assert out[1] == pytest.approx(5.0)
    assert out[2] == pytest.approx(1.0)  # (0*16 + 10*1.777)/17.777


def test_estimate_row_radius_excludes_far_points():
    out = _estimate_row(np.array([[0.5, 0.5]]), np.array([0.0, 10.0]), power=2.0, neighbours=0, radius=0.3)
    assert np.isnan(out[0])  # both points beyond the radius -> unestimated


def test_estimate_row_neighbours_limits_the_points_used():
    # Three points; with one neighbour only the nearest counts.
    dist = np.array([[0.1, 0.5, 0.9]])
    values = np.array([1.0, 2.0, 3.0])
    out = _estimate_row(dist, values, power=2.0, neighbours=1, radius=0.0)
    assert out[0] == pytest.approx(1.0)


def test_grid_keeps_aspect_ratio_and_pads():
    px = np.array([0.0, 2.0])
    py = np.array([0.0, 1.0])
    (minx, miny, maxx, maxy), (cx, cy), width, height = _grid(px, py, resolution=100)
    assert width == 100 and height == 50  # 2:1 extent
    assert minx < 0.0 and maxx > 2.0  # padded


def test_interpolate_a_symmetric_square():
    points = [SamplePointDTO(0, 0, 0.0), SamplePointDTO(1, 0, 10.0),
              SamplePointDTO(0, 1, 20.0), SamplePointDTO(1, 1, 30.0)]
    result = InterpolationService().interpolate_idw(points, "temp", IDWParamsDTO(power=2, resolution=60))
    assert result.crs == "EPSG:4326"
    assert result.point_count == 4 and result.field == "temp"
    assert result.stats["min"] == pytest.approx(0.0, abs=0.5)
    assert result.stats["max"] == pytest.approx(30.0, abs=0.5)
    assert result.stats["mean"] == pytest.approx(15.0, abs=1.0)  # symmetric
    assert result.rgba.shape[2] == 4 and np.isfinite(result.values).any()


def test_too_few_points_is_rejected():
    with pytest.raises(InterpolationError, match="two sample points"):
        InterpolationService().interpolate_idw([SamplePointDTO(0, 0, 1.0)], "x")


def test_radius_that_covers_nothing_is_reported():
    points = [SamplePointDTO(0, 0, 1.0), SamplePointDTO(10, 10, 2.0)]
    with pytest.raises(InterpolationError, match="radius"):
        InterpolationService().interpolate_idw(points, "x", IDWParamsDTO(radius=1e-6, resolution=30))


def test_save_surface_writes_a_geotiff(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    points = [SamplePointDTO(0, 0, 0.0), SamplePointDTO(1, 1, 10.0)]
    svc = InterpolationService()
    result = svc.interpolate_idw(points, "v", IDWParamsDTO(resolution=40))
    out = svc.save_surface(result, str(tmp_path / "idw.tif"))
    with rasterio.open(out) as src:
        assert src.crs.to_epsg() == 4326
        assert src.width == result.width and src.height == result.height
