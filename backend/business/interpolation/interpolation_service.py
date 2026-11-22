"""Inverse Distance Weighting (IDW), as ArcGIS's Spatial Analyst IDW tool does it.

A value is estimated at every output cell as a weighted average of the sample points, each
weighted by 1 / distance^power — nearer points count for more. A search can be limited to the
``neighbours`` nearest points and/or to points within a ``radius``; a cell with no points in
range is left unestimated (transparent). Points are in WGS84, so distances are in degrees; for
a small study area that matches what a desktop GIS shows. Everything is pure numpy — no SciPy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from backend.business.interpolation.i_interpolation_service import IInterpolationService
from backend.business.map.colour_maps import VIRIDIS
from backend.dto.interpolation_dto import IDWParamsDTO, IDWResultDTO, SamplePointDTO
from backend.dto.map_dto import LegendDTO
from backend.exceptions import InterpolationError

MAX_POINTS = 100_000
MAX_RESOLUTION = 1200


class InterpolationService(IInterpolationService):
    def interpolate_idw(self, points: Sequence[SamplePointDTO], field: str,
                        params: IDWParamsDTO | None = None) -> IDWResultDTO:
        params = params or IDWParamsDTO()
        px, py, pz = _sample_arrays(points)
        if px.size < 2:
            raise InterpolationError("At least two sample points with a numeric value are needed to interpolate.")
        if px.size > MAX_POINTS:
            raise InterpolationError(f"Too many sample points ({px.size:,}); the limit is {MAX_POINTS:,}.")
        if params.power <= 0:
            raise InterpolationError("The power must be greater than 0.")

        bounds, (cx, cy), width, height = _grid(px, py, params.resolution)
        xs = bounds[0] + (np.arange(width) + 0.5) * cx
        ys = bounds[3] - (np.arange(height) + 0.5) * cy  # top row first
        surface = np.full((height, width), np.nan, dtype="float64")
        neighbours = params.neighbours if 0 < params.neighbours < px.size else 0
        radius = params.radius if params.radius > 0 else 0.0

        for row in range(height):
            dx = xs[:, None] - px[None, :]
            dy = ys[row] - py[None, :]
            dist = np.sqrt(dx * dx + dy * dy)  # (width, n_points)
            surface[row] = _estimate_row(dist, pz, params.power, neighbours, radius)

        estimated = np.isfinite(surface)
        if not estimated.any():
            raise InterpolationError("No cell had a sample point within the search radius; widen it or use no radius.")
        rgba, legend, low, high = _draw(surface, estimated, field, bounds, (cx, cy), px, py)
        values = estimated_values = surface[estimated]
        stats = {"min": float(values.min()), "max": float(values.max()), "mean": float(values.mean())}
        notes = [f"{px.size:,} sample points · power {params.power:g}"
                 + (f" · {neighbours} neighbours" if neighbours else " · all points")
                 + (f" · radius {radius:g}°" if radius else "")]
        return IDWResultDTO(
            values=np.where(estimated, surface, np.nan).astype("float32"), rgba=rgba, legend=legend,
            width=width, height=height, bounds=bounds, cell_size=(cx, cy), crs="EPSG:4326",
            point_count=int(px.size), field=field, params=params, stats=stats, notes=notes,
        )

    def save_surface(self, result: IDWResultDTO, path: str) -> str:
        import rasterio
        from rasterio.transform import from_origin

        target = Path(path)
        if target.suffix.lower() not in (".tif", ".tiff"):
            target = target.with_suffix(".tif")
        values = np.asarray(result.values, dtype="float32")
        nodata = -9999.0
        out = np.where(np.isfinite(values), values, nodata).astype("float32")
        transform = from_origin(result.bounds[0], result.bounds[3], result.cell_size[0], result.cell_size[1])
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(str(target), "w", driver="GTiff", height=result.height, width=result.width,
                               count=1, dtype="float32", crs="EPSG:4326", transform=transform,
                               nodata=nodata) as dst:
                dst.write(out, 1)
        except (rasterio.errors.RasterioIOError, OSError) as exc:
            raise InterpolationError(f"The surface GeoTIFF could not be written: {exc}") from exc
        return str(target)


# ------------------------------------------------------------- maths (pure, testable)
def _estimate_row(dist: np.ndarray, values: np.ndarray, power: float, neighbours: int,
                  radius: float) -> np.ndarray:
    """One output row's estimates (shape (width,)); NaN where no point is in range."""
    width = dist.shape[0]
    out = np.full(width, np.nan)

    exact = dist <= 1e-12  # a cell sitting on a sample point takes that point's value exactly
    on_point = exact.any(axis=1)
    if on_point.any():
        first = np.argmax(exact[on_point], axis=1)
        out[on_point] = values[first]

    todo = ~on_point
    if not todo.any():
        return out
    d = dist[todo]
    if radius > 0:
        d = np.where(d <= radius, d, np.inf)
    weights = 1.0 / np.power(d, power)
    if neighbours:
        keep = np.argsort(d, axis=1)[:, :neighbours]  # the nearest N per cell
        mask = np.zeros_like(weights, dtype=bool)
        np.put_along_axis(mask, keep, True, axis=1)
        weights = np.where(mask, weights, 0.0)
    weights[~np.isfinite(weights)] = 0.0
    total = weights.sum(axis=1)
    estimate = np.where(total > 0, (weights * values[None, :]).sum(axis=1) / np.where(total > 0, total, 1.0), np.nan)
    out[todo] = estimate
    return out


def _sample_arrays(points: Sequence[SamplePointDTO]):
    px = np.array([p.lon for p in points], dtype="float64")
    py = np.array([p.lat for p in points], dtype="float64")
    pz = np.array([p.value for p in points], dtype="float64")
    finite = np.isfinite(px) & np.isfinite(py) & np.isfinite(pz)
    return px[finite], py[finite], pz[finite]


def _grid(px: np.ndarray, py: np.ndarray, resolution: int):
    """The output extent (padded) and grid: (bounds, (cell_x, cell_y), width, height)."""
    resolution = int(max(16, min(MAX_RESOLUTION, resolution)))
    minx, maxx = float(px.min()), float(px.max())
    miny, maxy = float(py.min()), float(py.max())
    span_x, span_y = maxx - minx, maxy - miny
    pad_x = span_x * 0.05 or 0.01
    pad_y = span_y * 0.05 or 0.01
    minx, maxx, miny, maxy = minx - pad_x, maxx + pad_x, miny - pad_y, maxy + pad_y
    span_x, span_y = maxx - minx, maxy - miny
    if span_x >= span_y:
        width = resolution
        height = max(1, int(round(resolution * span_y / span_x)))
    else:
        height = resolution
        width = max(1, int(round(resolution * span_x / span_y)))
    return (minx, miny, maxx, maxy), (span_x / width, span_y / height), width, height


def _draw(surface, estimated, field, bounds, cell, px, py):
    low = float(np.nanpercentile(surface[estimated], 2))
    high = float(np.nanpercentile(surface[estimated], 98))
    if high <= low:
        high = low + 1e-9
    scaled = np.clip((surface - low) / (high - low), 0.0, 1.0)
    rgb = VIRIDIS.apply(np.where(estimated, scaled, 0.0))
    _mark_points(rgb, estimated.shape, bounds, cell, px, py)
    alpha = np.where(estimated, 255, 0).astype(np.uint8)
    rgba = np.dstack([rgb.astype(np.uint8), alpha])
    legend = LegendDTO("scale", f"{field} (IDW)", low=low, high=high, colours=VIRIDIS.colours())
    return rgba, legend, low, high


def _mark_points(rgb, shape, bounds, cell, px, py) -> None:
    """Dot each sample point onto the surface so the control points are visible."""
    height, width = shape
    cx, cy = cell
    cols = ((px - bounds[0]) / cx).astype(int)
    rows = ((bounds[3] - py) / cy).astype(int)
    for col, r in zip(cols, rows):
        if 0 <= r < height and 0 <= col < width:
            r0, r1 = max(0, r - 1), min(height, r + 2)
            c0, c1 = max(0, col - 1), min(width, col + 2)
            rgb[r0:r1, c0:c1] = (20, 20, 20)
            rgb[r, col] = (255, 255, 255)
