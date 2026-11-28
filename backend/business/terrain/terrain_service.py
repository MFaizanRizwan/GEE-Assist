"""Reads a Digital Elevation Model (DEM) and derives terrain surfaces, as ArcGIS's
Spatial Analyst "Surface" tools do: shaded-relief elevation, hillshade, slope, aspect
and contours.

The DEM's first band is the elevation. Slope and aspect use Horn's 3x3 method and
hillshade uses the ESRI formula, so results match what desktop GIS users expect. Previews
are computed on a downsampled copy (so large DEMs draw quickly); ``save_product`` recomputes
at full resolution and writes a GeoTIFF. No plotting library is needed — colour ramps come
from ``colour_maps`` and contours from a small marching-squares implementation.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.business.map.colour_maps import GREYS, ColourMap
from backend.business.terrain.i_terrain_service import ITerrainService
from backend.dto.map_dto import LegendDTO
from backend.dto.terrain_dto import TerrainInfoDTO, TerrainProductDTO
from backend.exceptions import TerrainError

# Hypsometric tint (low land -> high land) and a slope ramp (gentle -> steep).
TERRAIN = ColourMap("Terrain", ((0.0, "#2A6B2E"), (0.25, "#8DB04A"), (0.5, "#D9C77E"),
                                (0.75, "#9C6B3B"), (1.0, "#FFFFFF")))
SLOPE = ColourMap("Slope", ((0.0, "#1A9850"), (0.5, "#FEE08B"), (1.0, "#D73027")))

# Aspect classified into eight compass directions (plus flat), each with a distinct colour.
ASPECT_CLASSES: tuple[tuple[str, str], ...] = (
    ("Flat", "#B0B0B0"), ("North", "#E8402C"), ("Northeast", "#E88B2C"), ("East", "#E8E22C"),
    ("Southeast", "#8BE82C"), ("South", "#2CE87A"), ("Southwest", "#2CD6E8"),
    ("West", "#2C72E8"), ("Northwest", "#8B2CE8"),
)

DEFAULT_AZIMUTH = 315.0
DEFAULT_ALTITUDE = 45.0
MAX_PREVIEW = 1600


class TerrainService(ITerrainService):
    def describe(self, path: str) -> TerrainInfoDTO:
        import rasterio

        file = Path(path)
        if not file.is_file():
            raise TerrainError(f"The DEM is not there: {file}")
        try:
            with rasterio.open(str(file)) as src:
                band = src.read(1, masked=True).astype("float64")
                res_x, res_y = src.res
                bounds = src.bounds
                crs = src.crs
                is_geographic = bool(crs.is_geographic) if crs is not None else False
                nodata = src.nodata
                width, height = src.width, src.height
        except rasterio.errors.RasterioIOError as exc:
            raise TerrainError(f"The DEM could not be read: {exc}") from exc
        valid = ~np.ma.getmaskarray(band)
        if not valid.any():
            raise TerrainError("The DEM has no elevation values (every pixel is no-data).")
        values = np.asarray(band)[valid]
        return TerrainInfoDTO(
            path=str(file), name=file.stem, width=width, height=height,
            crs=(crs.to_string() if crs is not None else "unknown"),
            bounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
            nodata=(float(nodata) if nodata is not None else None),
            cell_size=(abs(float(res_x)), abs(float(res_y))), is_geographic=is_geographic,
            unit="m", min_elevation=float(values.min()), max_elevation=float(values.max()),
            mean_elevation=float(values.mean()), size_bytes=(file.stat().st_size if file.exists() else 0),
        )

    # ------------------------------------------------------------- rendering
    def render(self, info: TerrainInfoDTO, product: str, params: dict[str, Any] | None = None,
               max_size: int = MAX_PREVIEW) -> TerrainProductDTO:
        params = params or {}
        z, valid, scale, cell = self._read(info, max_size)
        notes = [f"Shown at 1/{scale:.1f} of full resolution."] if scale > 1 else []
        rgba, legend, values, unit, label = self._surface(z, valid, cell, product, params)
        height, width = z.shape
        return TerrainProductDTO(key=product, label=label, rgba=rgba, legend=legend, width=width,
                                 height=height, scale=scale, values=values, unit=unit, notes=notes)

    def save_product(self, info: TerrainInfoDTO, product: str, path: str,
                     params: dict[str, Any] | None = None) -> str:
        import rasterio

        params = params or {}
        z, valid, _scale, cell = self._read(info, max_size=max(info.width, info.height))  # full resolution
        _rgba, _legend, values, _unit, _label = self._surface(z, valid, cell, product, params)
        if values is None:
            raise TerrainError(f"{product} cannot be saved as a GeoTIFF.")
        target = Path(path)
        if target.suffix.lower() not in (".tif", ".tiff"):
            target = target.with_suffix(".tif")
        nodata = -9999.0
        out = np.where(np.isfinite(values), values, nodata).astype("float32")
        try:
            with rasterio.open(info.path) as src:
                profile = src.profile
            profile.update(count=1, dtype="float32", nodata=nodata)
            target.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(str(target), "w", **profile) as dst:
                dst.write(out, 1)
        except (rasterio.errors.RasterioIOError, OSError) as exc:
            raise TerrainError(f"The {product} GeoTIFF could not be written: {exc}") from exc
        return str(target)

    # ------------------------------------------------------------- the surfaces
    def _surface(self, z: np.ndarray, valid: np.ndarray, cell: tuple[float, float], product: str,
                 params: dict[str, Any]):
        z_factor = float(params.get("z_factor", 1.0))
        if product == "hillshade":
            azimuth = float(params.get("azimuth", DEFAULT_AZIMUTH))
            altitude = float(params.get("altitude", DEFAULT_ALTITUDE))
            shade = hillshade(z, cell, z_factor, azimuth, altitude)
            rgb = GREYS.apply(shade / 255.0)
            legend = LegendDTO("scale", "Hillshade (0–255)", low=0, high=255, colours=GREYS.colours())
            return self._rgba(rgb, valid), legend, _masked(shade, valid), "", "Hillshade"
        if product == "slope":
            slope = slope_degrees(z, cell, z_factor)
            high = max(1.0, float(np.nanpercentile(np.where(valid, slope, np.nan), 98)))
            rgb = SLOPE.apply(slope / high)
            legend = LegendDTO("scale", "Slope (degrees)", low=0.0, high=high, colours=SLOPE.colours())
            return self._rgba(rgb, valid), legend, _masked(slope, valid), "°", "Slope"
        if product == "aspect":
            classes = aspect_classes(z, cell)  # 0 = flat, 1..8 = N, NE, ... NW
            palette = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in ASPECT_CLASSES], dtype=np.uint8)
            rgb = palette[np.clip(classes, 0, 8)]
            present = sorted(set(np.unique(classes[valid]).tolist()))
            legend = LegendDTO("classes", "Aspect",
                               colours=tuple(ASPECT_CLASSES[i][1] for i in present),
                               labels=tuple(ASPECT_CLASSES[i][0] for i in present))
            return self._rgba(rgb, valid), legend, _masked(classes.astype("float32"), valid), "", "Aspect"
        if product == "contours":
            return self._contours(z, valid, cell, params)
        # elevation (shaded relief) — the default
        low, high = _finite_range(z, valid)
        norm = np.clip((z - low) / (high - low), 0.0, 1.0)
        rgb = TERRAIN.apply(norm).astype("float64")
        shade = hillshade(z, cell, z_factor, DEFAULT_AZIMUTH, DEFAULT_ALTITUDE) / 255.0
        rgb = np.clip(rgb * (0.45 + 0.55 * shade[..., None]), 0, 255).astype(np.uint8)  # drape relief over the tint
        legend = LegendDTO("scale", "Elevation (m)", low=low, high=high, colours=TERRAIN.colours())
        return self._rgba(rgb, valid), legend, _masked(z, valid), "m", "Elevation (shaded relief)"

    def _contours(self, z: np.ndarray, valid: np.ndarray, cell: tuple[float, float], params: dict[str, Any]):
        low, high = _finite_range(z, valid)
        interval = float(params.get("interval") or _nice_interval(high - low))
        interval = max(interval, 1e-6)
        shade = hillshade(z, cell, 1.0, DEFAULT_AZIMUTH, DEFAULT_ALTITUDE) / 255.0
        rgb = np.clip(200 + 55 * shade, 0, 255).astype(np.uint8)  # pale shaded-relief backdrop
        rgb = np.dstack([rgb, rgb, rgb])
        filled = np.where(valid, z, np.nan)
        level = math.ceil(low / interval) * interval
        levels = []
        line = np.array([70, 70, 70], dtype=np.uint8)
        while level < high:
            levels.append(level)
            level += interval
        # every level at once: each cell meets only the levels between its corners
        for x0, y0, x1, y1 in _ContourCells(filled).segments_for(levels):
            _draw_segments(rgb, x0, y0, x1, y1, line)
        legend = LegendDTO("scale", f"Contours every {interval:g} m", low=low, high=high,
                           colours=TERRAIN.colours())
        rgba = self._rgba(rgb, valid)
        note = f"{len(levels)} contour levels at {interval:g} m."
        product = TerrainProductDTO(key="contours", label="Contours", rgba=rgba, legend=legend,
                                    width=z.shape[1], height=z.shape[0], scale=1.0, values=None, unit="m",
                                    notes=[note])
        return product.rgba, product.legend, None, "m", "Contours"

    @staticmethod
    def _rgba(rgb: np.ndarray, valid: np.ndarray) -> np.ndarray:
        alpha = np.where(valid, 255, 0).astype(np.uint8)
        return np.dstack([rgb.astype(np.uint8), alpha])

    # ------------------------------------------------------------- reading
    def _read(self, info: TerrainInfoDTO, max_size: int):
        """The elevation at preview size: (z float64, valid mask, scale, (cell_x_m, cell_y_m))."""
        import rasterio
        from rasterio.enums import Resampling

        scale = max(1.0, max(info.width, info.height) / max_size)
        height = max(2, math.ceil(info.height / scale))
        width = max(2, math.ceil(info.width / scale))
        try:
            with rasterio.open(info.path) as src:
                data = src.read(1, out_shape=(height, width), resampling=Resampling.average, out_dtype="float64")
        except rasterio.errors.RasterioIOError as exc:
            raise TerrainError(f"Cannot read {info.name}: {exc}") from exc
        valid = np.isfinite(data)
        if info.nodata is not None:
            valid &= data != info.nodata
        z = np.where(valid, data, np.nan)
        cell = self._cell_metres(info, scale, width, height)
        return z, valid, scale, cell

    def _cell_metres(self, info: TerrainInfoDTO, scale: float, width: int, height: int) -> tuple[float, float]:
        """The preview's cell size in metres (so slope is in real degrees of incline)."""
        cx, cy = info.cell_size
        cx *= info.width / width   # the downsample makes each preview cell cover more ground
        cy *= info.height / height
        if info.is_geographic:
            west, south, east, north = info.bounds
            mean_lat = math.radians((south + north) / 2)
            cx *= 111_320.0 * max(0.1, math.cos(mean_lat))
            cy *= 110_540.0
        return cx, cy


# ------------------------------------------------------------- terrain maths (pure, testable)
def _horn_gradients(z: np.ndarray, cell: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """dz/dx and dz/dy by Horn's 3x3 method; no-data (NaN) neighbours fall back to the centre."""
    cx, cy = cell
    filled = np.where(np.isfinite(z), z, np.nan)
    mean = np.nanmean(filled) if np.isfinite(filled).any() else 0.0
    zp = np.pad(np.where(np.isfinite(filled), filled, mean), 1, mode="edge")
    a, b, c = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    d, _f_e, f = zp[1:-1, :-2], zp[1:-1, 1:-1], zp[1:-1, 2:]
    g, h, i = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * cx)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * cy)
    return dzdx, dzdy


def slope_degrees(z: np.ndarray, cell: tuple[float, float], z_factor: float = 1.0) -> np.ndarray:
    dzdx, dzdy = _horn_gradients(z, cell)
    rise_run = np.sqrt(dzdx ** 2 + dzdy ** 2) * z_factor
    return np.degrees(np.arctan(rise_run))


def aspect_classes(z: np.ndarray, cell: tuple[float, float]) -> np.ndarray:
    """Aspect per cell as a compass class: 0 = flat, 1 = N, 2 = NE, ... 8 = NW."""
    dzdx, dzdy = _horn_gradients(z, cell)
    aspect = np.degrees(np.arctan2(dzdy, -dzdx))
    compass = np.where(aspect < 0, 90.0 - aspect, np.where(aspect > 90.0, 450.0 - aspect, 90.0 - aspect))
    compass = np.mod(compass, 360.0)
    sector = (np.floor((compass + 22.5) / 45.0).astype(int) % 8) + 1  # 1..8 around the compass
    flat = (dzdx == 0) & (dzdy == 0)
    sector[flat] = 0
    return sector


def hillshade(z: np.ndarray, cell: tuple[float, float], z_factor: float = 1.0,
              azimuth: float = DEFAULT_AZIMUTH, altitude: float = DEFAULT_ALTITUDE) -> np.ndarray:
    """ESRI hillshade (0–255) for the given sun azimuth and altitude (degrees)."""
    dzdx, dzdy = _horn_gradients(z, cell)
    slope_rad = np.arctan(z_factor * np.sqrt(dzdx ** 2 + dzdy ** 2))
    aspect_rad = np.arctan2(dzdy, -dzdx)
    aspect_rad = np.where(aspect_rad < 0, 2 * np.pi + aspect_rad, aspect_rad)
    zenith = math.radians(90.0 - altitude)
    az = math.radians(360.0 - azimuth + 90.0)
    shade = (math.cos(zenith) * np.cos(slope_rad)
             + math.sin(zenith) * np.sin(slope_rad) * np.cos(az - aspect_rad))
    return np.clip(shade * 255.0, 0, 255)


def contour_segments(z: np.ndarray, level: float) -> list[tuple[float, float, float, float]]:
    """Line segments (x0, y0, x1, y1), in pixel coordinates, where ``z`` crosses ``level``
    (marching squares with linear interpolation). Cells touching no-data are skipped.

    Row by row, left to right, as a cell-by-cell scan gives them."""
    x0, y0, x1, y1 = _ContourCells(z).segments(level)
    return list(zip(x0.tolist(), y0.tolist(), x1.tolist(), y1.tolist()))


class _ContourCells:
    """Marching squares over the whole grid at once (numpy), for one level at a time.

    It used to visit every cell of the grid in Python, for every level: minutes on a
    country-sized DEM. The arithmetic is the same, value for value: the same case test
    (corner >= level), the same interpolation ((level - a) / (b - a), clipped to 0-1, or
    0.5 on a flat edge), added to the same whole-number cell position. So the segments,
    and the contour picture, are exactly those of the cell-by-cell scan."""

    def __init__(self, z: np.ndarray):
        z = np.asarray(z, dtype="float64")
        self.tl, self.tr = z[:-1, :-1], z[:-1, 1:]
        self.bl, self.br = z[1:, :-1], z[1:, 1:]
        # cells whose four corners all have data
        self.complete = (np.isfinite(self.tl) & np.isfinite(self.tr)
                         & np.isfinite(self.bl) & np.isfinite(self.br))

    def segments(self, level: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(x0, y0, x1, y1) arrays, in the order of a row-by-row, left-to-right scan (a
        saddle cell's two segments in the order of ``_CASE_EDGES``)."""
        with np.errstate(invalid="ignore"):   # NaN corners compare False; those cells are skipped
            case = ((self.tl >= level).astype(np.int8) << 3) | ((self.tr >= level).astype(np.int8) << 2) \
                | ((self.br >= level).astype(np.int8) << 1) | (self.bl >= level).astype(np.int8)
        crossed = self.complete & (case != 0) & (case != 15)
        rows, cols = np.nonzero(crossed)               # row-major: the scan's order
        return self._segments_at(rows, cols, level)

    def segments_for(self, levels: list[float], batch: int = 2_000_000):
        """The segments of every level, as (x0, y0, x1, y1) arrays in batches (for drawing).

        A level crosses a cell exactly when the cell's lowest corner is below it and its
        highest corner is not (any other case is 0 or 15, which draws nothing). So instead
        of scanning the whole grid once per level, each cell is paired with just the levels
        between its corners, found by binary search in the sorted levels. Each pair is then
        worked out with the same comparisons and arithmetic as ``segments``, at the same
        level value. (Batches keep memory bounded; drawing order does not change pixels.)"""
        if not levels:
            return
        values = np.asarray(levels, dtype="float64")       # the exact level values, ascending
        rows, cols = np.nonzero(self.complete)
        corners = np.stack([self.tl[rows, cols], self.tr[rows, cols], self.bl[rows, cols], self.br[rows, cols]])
        low, high = corners.min(axis=0), corners.max(axis=0)
        first = np.searchsorted(values, low, side="right")          # first level above the lowest corner
        last = np.searchsorted(values, high, side="right") - 1       # last level at or below the highest
        count = np.maximum(last - first + 1, 0)
        keep = np.nonzero(count)[0]
        rows, cols, first, count = rows[keep], cols[keep], first[keep], count[keep]
        ends = np.cumsum(count)
        start = 0
        while start < len(count):
            # whole cells per batch, about ``batch`` (cell, level) pairs each
            stop = int(np.searchsorted(ends, (ends[start - 1] if start else 0) + batch, side="right"))
            stop = max(stop, start + 1)
            n = count[start:stop]
            cell = np.repeat(np.arange(start, stop), n)
            k = np.repeat(first[start:stop], n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
            yield self._segments_at(rows[cell], cols[cell], values[k])
            start = stop

    def _segments_at(self, rows: np.ndarray, cols: np.ndarray, level):
        """The segments of cells (rows, cols), each at ``level`` (one value, or one per cell)."""
        if rows.size == 0:
            empty = np.empty(0, dtype="float64")
            return empty, empty, empty, empty
        tl, tr = self.tl[rows, cols], self.tr[rows, cols]
        bl, br = self.bl[rows, cols], self.br[rows, cols]
        case = ((tl >= level).astype(np.int8) << 3) | ((tr >= level).astype(np.int8) << 2) \
            | ((br >= level).astype(np.int8) << 1) | (bl >= level).astype(np.int8)
        r, c = rows.astype("float64"), cols.astype("float64")
        # the crossing on each edge: T, R, B, L (the indices _EDGE_INDEX uses)
        xs = np.stack([c + _interp_array(tl, tr, level), c + 1.0, c + _interp_array(bl, br, level), c])
        ys = np.stack([r, r + _interp_array(tr, br, level), r + 1.0, r + _interp_array(tl, bl, level)])
        cell = np.arange(case.size)

        first_p, first_q = _FIRST[0][case], _FIRST[1][case]
        x0, y0 = xs[first_p, cell], ys[first_p, cell]
        x1, y1 = xs[first_q, cell], ys[first_q, cell]
        saddle = np.nonzero(_SECOND[0][case] >= 0)[0]  # cases 5 and 10 join two pairs of edges
        if saddle.size == 0:
            return x0, y0, x1, y1
        second_p, second_q = _SECOND[0][case[saddle]], _SECOND[1][case[saddle]]
        # each saddle's second segment goes right after its first
        order = np.argsort(np.concatenate([cell * 2, saddle * 2 + 1]), kind="stable")

        def merged(first: np.ndarray, second: np.ndarray) -> np.ndarray:
            return np.concatenate([first, second])[order]

        return (merged(x0, xs[second_p, saddle]), merged(y0, ys[second_p, saddle]),
                merged(x1, xs[second_q, saddle]), merged(y1, ys[second_q, saddle]))


# Which edges a marching-squares case joins (T top, R right, B bottom, L left).
_CASE_EDGES: dict[int, tuple[tuple[str, str], ...]] = {
    1: (("L", "B"),), 2: (("B", "R"),), 3: (("L", "R"),), 4: (("T", "R"),),
    5: (("L", "T"), ("B", "R")), 6: (("T", "B"),), 7: (("L", "T"),),
    8: (("L", "T"),), 9: (("T", "B"),), 10: (("L", "B"), ("T", "R")), 11: (("T", "R"),),
    12: (("L", "R"),), 13: (("B", "R"),), 14: (("L", "B"),),
}


_EDGE_INDEX = {"T": 0, "R": 1, "B": 2, "L": 3}
# per case: the edge indices of its first (and, for a saddle, second) segment; -1 for none
_FIRST = (np.full(16, 0, dtype=np.intp), np.full(16, 0, dtype=np.intp))
_SECOND = (np.full(16, -1, dtype=np.intp), np.full(16, -1, dtype=np.intp))
for _case, _pairs in _CASE_EDGES.items():
    _FIRST[0][_case], _FIRST[1][_case] = (_EDGE_INDEX[e] for e in _pairs[0])
    if len(_pairs) > 1:
        _SECOND[0][_case], _SECOND[1][_case] = (_EDGE_INDEX[e] for e in _pairs[1])


def _interp(a: float, b: float, level: float) -> float:
    if a == b:
        return 0.5
    return float(np.clip((level - a) / (b - a), 0.0, 1.0))


def _interp_array(a: np.ndarray, b: np.ndarray, level: float) -> np.ndarray:
    """``_interp`` for whole arrays, value for value."""
    with np.errstate(divide="ignore", invalid="ignore"):   # flat edges are replaced by 0.5
        t = np.clip((level - a) / (b - a), 0.0, 1.0)
    return np.where(a == b, 0.5, t)


def _draw_segments(rgb: np.ndarray, x0: np.ndarray, y0: np.ndarray, x1: np.ndarray, y1: np.ndarray,
                   colour: np.ndarray) -> None:
    """``_draw_line`` for every segment at once, pixel for pixel.

    A marching-squares segment lies inside one grid cell, so its rounded ends are at most
    one pixel apart in x and in y. For such a line Bresenham's algorithm sets exactly its
    two end pixels (straight or diagonal), so setting the rounded ends is the same picture.
    Rounding is half-to-even, as Python's ``round``. Longer segments (none, from marching
    squares) are drawn one by one with ``_draw_line``."""
    if x0.size == 0:
        return
    ix0, iy0, ix1, iy1 = (np.rint(v).astype(np.int64) for v in (x0, y0, x1, y1))
    short = (np.abs(ix1 - ix0) <= 1) & (np.abs(iy1 - iy0) <= 1)
    h, w = rgb.shape[:2]
    for xs, ys in ((ix0[short], iy0[short]), (ix1[short], iy1[short])):
        inside = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        rgb[ys[inside], xs[inside]] = colour
    for i in np.nonzero(~short)[0]:
        _draw_line(rgb, x0[i], y0[i], x1[i], y1[i], colour)


def _draw_line(rgb: np.ndarray, x0: float, y0: float, x1: float, y1: float, colour: np.ndarray) -> None:
    """Rasterise a thin line into ``rgb`` (Bresenham)."""
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    h, w = rgb.shape[:2]
    while True:
        if 0 <= y0 < h and 0 <= x0 < w:
            rgb[y0, x0] = colour
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def _masked(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    return np.where(valid, values, np.nan).astype("float32")


def _finite_range(z: np.ndarray, valid: np.ndarray) -> tuple[float, float]:
    if not valid.any():
        return 0.0, 1.0
    values = z[valid]
    low, high = float(np.min(values)), float(np.max(values))
    if high <= low:
        high = low + 1.0
    return low, high


def _nice_interval(span: float) -> float:
    """A round contour interval (~10 lines across the range): 1, 2, 5, 10, 20, 50, ..."""
    if span <= 0:
        return 1.0
    rough = span / 10.0
    power = 10 ** math.floor(math.log10(rough))
    for step in (1, 2, 5, 10):
        if step * power >= rough:
            return step * power
    return 10 * power
