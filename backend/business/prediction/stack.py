"""Bring a time series of GeoTIFFs onto one grid: the present image's, at a working size.

Downloads of the same place on different dates rarely line up pixel for pixel (another
extent, cell size or projection). Each file is warped onto the present image's grid,
shrunk so its longer side is at most ``working_size`` cells: continuous values are
averaged (bilinear when not shrinking), class codes take the nearest pixel.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from backend.exceptions import PredictionError

_DATE = re.compile(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})")


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    transform: object          # rasterio Affine
    crs: object                # rasterio CRS
    bounds_wgs84: tuple[float, float, float, float]
    scale: float               # source pixels per working pixel

    def coordinates(self) -> tuple[np.ndarray, np.ndarray]:
        """Each cell's centre, scaled 0-1 across the grid (x east, y north), as (height, width) arrays."""
        xs = (np.arange(self.width) + 0.5) / self.width
        ys = 1.0 - (np.arange(self.height) + 0.5) / self.height
        return np.meshgrid(xs, ys)


def parse_date(text: str) -> date:
    match = _DATE.search(text or "")
    if not match:
        raise PredictionError(f"Not a date: {text!r} (use YYYY-MM-DD).")
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError as exc:
        raise PredictionError(f"Not a date: {text!r}.") from exc


def guess_date(path: str, tags: dict | None = None) -> str:
    """The date a GeoTIFF shows, from its download name (the end of its date range) or its tags."""
    from backend.business.download.naming import parse_dataset_name

    file = Path(path)
    for name in (file.stem, file.parent.name):
        _satellite, start, end = parse_dataset_name(name)
        if end or start:
            return end or start
    for key in ("date", "DATE", "DATE_ACQUIRED", "TIFFTAG_DATETIME", "system:time_start", "end_date"):
        value = (tags or {}).get(key)
        if value and _DATE.search(str(value)):
            return parse_date(str(value)).isoformat()
    match = _DATE.search(file.stem)
    if match:
        try:
            return parse_date(match.group(0)).isoformat()
        except PredictionError:
            return ""
    return ""


def band_names(src) -> tuple[str, ...]:
    return tuple(name or f"Band {index}" for index, name in enumerate(src.descriptions, start=1))


def band_index(src, band: str) -> int:
    """The 1-based index of ``band`` (its name, or "Band N"), else an error naming the choices."""
    names = band_names(src)
    if band in names:
        return names.index(band) + 1
    lowered = [n.lower() for n in names]
    if band.lower() in lowered:
        return lowered.index(band.lower()) + 1
    raise PredictionError(f"{Path(src.name).name} has no band {band!r} (it has: {', '.join(names)}).")


def working_grid(present_path: str, working_size: int) -> Grid:
    import rasterio
    from rasterio.transform import Affine
    from rasterio.warp import transform_bounds

    try:
        with rasterio.open(present_path) as src:
            width, height, transform, crs = src.width, src.height, src.transform, src.crs
    except rasterio.errors.RasterioIOError as exc:
        raise PredictionError(f"Cannot open {Path(present_path).name}: {exc}") from exc
    if crs is None:
        raise PredictionError(f"{Path(present_path).name} has no coordinate system.")
    scale = max(1.0, max(width, height) / max(16, working_size))
    w, h = max(2, math.ceil(width / scale)), max(2, math.ceil(height / scale))
    grid_transform = transform * Affine.scale(width / w, height / h)
    west, north = grid_transform * (0, 0)
    east, south = grid_transform * (w, h)
    bounds = transform_bounds(crs, "EPSG:4326", min(west, east), min(south, north), max(west, east),
                              max(south, north))
    return Grid(w, h, grid_transform, crs, tuple(bounds), scale)


def read_band(path: str, band: str, grid: Grid, categorical: bool = False) -> np.ndarray:
    """``band`` of ``path`` on ``grid`` (float64, NaN where there is no data)."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    try:
        with rasterio.open(path) as src:
            index = band_index(src, band)
            if categorical:
                resampling = Resampling.nearest
            else:
                shrink = abs(grid.transform.a) > abs(src.transform.a) * 1.01
                resampling = Resampling.average if shrink else Resampling.bilinear
            nodata = src.nodatavals[index - 1]
            with WarpedVRT(src, crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height,
                           resampling=resampling, src_nodata=nodata, nodata=nodata if nodata is not None else np.nan,
                           dtype="float64") as vrt:
                data = vrt.read(index, masked=True).astype("float64")
    except rasterio.errors.RasterioIOError as exc:
        raise PredictionError(f"Cannot read {Path(path).name}: {exc}") from exc
    values = data.filled(np.nan)
    if nodata is not None and np.isfinite(nodata):
        values[values == nodata] = np.nan
    values[values <= -9998.5] = np.nan   # the app's own no-data value
    return values


def read_bands(path: str, grid: Grid) -> tuple[np.ndarray, tuple[str, ...]]:
    """Every band of ``path`` on ``grid``: (bands, height, width) and their names."""
    import rasterio

    with rasterio.open(path) as src:
        names = band_names(src)
    return np.stack([read_band(path, name, grid) for name in names]), names


def looks_categorical(values: np.ndarray) -> bool:
    """Whole numbers with few distinct values: class codes rather than measurements."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return False
    if not np.allclose(finite, np.round(finite)):
        return False
    return np.unique(finite).size <= 40
