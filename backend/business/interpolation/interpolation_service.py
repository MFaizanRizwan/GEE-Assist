"""Inverse Distance Weighting (IDW), as ArcGIS's Spatial Analyst IDW tool does it.

A value is estimated at every output cell as a weighted average of the sample points, each
weighted by 1 / distance^power — nearer points count for more. A search can be limited to the
``neighbours`` nearest points and/or to points within a ``radius``; a cell with no points in
range is left unestimated (transparent). Points are in WGS84, so distances are in degrees; for
a small study area that matches what a desktop GIS shows. Everything is pure numpy — no SciPy.

Speed: the cells are worked out in blocks on every CPU core (numpy lets go of Python's lock
while it computes), and the nearest ``neighbours`` are picked by a partial selection instead
of sorting every point for every cell. The arithmetic per cell is unchanged, so the surface
is the same, value for value (see ``_estimate_row``).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
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
BLOCK_BYTES = 48 * 1024 * 1024   # about this much per (cells x points) array in one block


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

        _fill_surface(surface, xs, ys, px, py, pz, params.power, neighbours, radius)

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
def _fill_surface(surface: np.ndarray, xs: np.ndarray, ys: np.ndarray, px: np.ndarray, py: np.ndarray,
                  pz: np.ndarray, power: float, neighbours: int, radius: float) -> None:
    """Estimate every cell of ``surface`` (height x width), in blocks of cells on all cores.

    A block is any run of cells in row order; each cell's distances and estimate are worked
    out exactly as for a whole row, so the blocking changes nothing but the speed."""
    if neighbours and _fill_nearest_tiles(surface, xs, ys, px, py, pz, power, neighbours, radius):
        return  # each cell measured against nearby points only (same values)
    height, width = surface.shape
    flat = surface.reshape(-1)
    cells = height * width
    per_block = max(1, min(cells, BLOCK_BYTES // max(1, 8 * px.size)))
    starts = range(0, cells, per_block)

    def block(start: int) -> None:
        stop = min(cells, start + per_block)
        index = np.arange(start, stop)
        dx = xs[index % width][:, None] - px[None, :]
        dy = ys[index // width][:, None] - py[None, :]
        dist = np.sqrt(dx * dx + dy * dy)  # (cells, n_points)
        flat[start:stop] = _estimate_row(dist, pz, power, neighbours, radius)

    workers = min(len(starts), os.cpu_count() or 1)
    if workers <= 1:
        for start in starts:
            block(start)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(block, starts))   # re-raises the first error


def _estimate_row(dist: np.ndarray, values: np.ndarray, power: float, neighbours: int,
                  radius: float) -> np.ndarray:
    """Estimates for a run of cells (one per row of ``dist``); NaN where no point is in range."""
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
    if neighbours:
        weights = _nearest_weights(d, power, neighbours)
    else:
        weights = 1.0 / np.power(d, power)
    weights[~np.isfinite(weights)] = 0.0
    total = weights.sum(axis=1)
    estimate = np.where(total > 0, (weights * values[None, :]).sum(axis=1) / np.where(total > 0, total, 1.0), np.nan)
    out[todo] = estimate
    return out


def _nearest_weights(d: np.ndarray, power: float, neighbours: int) -> np.ndarray:
    """1 / d^power for each cell's ``neighbours`` nearest points, 0 for the others.

    Was: sort all the points of every cell (``argsort``) and keep the first N, which was
    nearly all the time IDW took. Now a partial selection (``argpartition``, linear time)
    finds the N nearest. That set is the same as the sort's unless several points tie at
    the N-th distance; then which of them a sort keeps is its own choice, so those cells are
    sorted exactly as before. Each kept weight is the same ``1 / d^power`` at the same place
    in the row, so the sums (and the surface) are identical."""
    cells, n = d.shape
    part = np.argpartition(d, neighbours - 1, axis=1)[:, :neighbours]
    nearest = np.take_along_axis(d, part, axis=1)
    weights = np.zeros_like(d)
    np.put_along_axis(weights, part, 1.0 / np.power(nearest, power), axis=1)
    kth = nearest.max(axis=1)
    # ties at a finite N-th distance: the sort's choice decides (beyond a radius, d is inf and
    # every such point weighs 0, whichever is kept)
    tied = np.isfinite(kth) & ((d <= kth[:, None]).sum(axis=1) > neighbours)
    if tied.any():
        rows = np.nonzero(tied)[0]
        dt = d[rows]
        keep = np.argsort(dt, axis=1)[:, :neighbours]  # as before, for these cells
        exact = np.zeros_like(dt)
        np.put_along_axis(exact, keep, 1.0 / np.power(np.take_along_axis(dt, keep, axis=1), power), axis=1)
        weights[rows] = exact
    return weights


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


# ------------------------------------------------------------- the fast path: nearby points only
TILE = 32   # cells per side of a tile that shares one set of candidate points


def _fill_nearest_tiles(surface: np.ndarray, xs: np.ndarray, ys: np.ndarray, px: np.ndarray, py: np.ndarray,
                        pz: np.ndarray, power: float, neighbours: int, radius: float) -> bool:
    """Fill ``surface`` measuring each cell only against points that can be among its nearest.

    Returns False (and fills nothing) when numpy's summation could not be reproduced exactly
    here; the caller then uses the full-row path. Otherwise every value is the one
    ``_estimate_row`` gives over all the points, bit for bit:

    * The cells of a tile share one set of candidate points: any point that could be among
      the ``neighbours`` nearest of some cell of the tile (its distance to the tile is at most
      the N-th smallest farthest distance to the tile), with a margin for rounding. The cell's
      distances are computed exactly as before, so its nearest N are the same points.
    * The two sums are numpy's own pairwise sums of the full row (which is zero except at the
      kept points), rebuilt from the kept points alone (``_PairwiseSum``).
    * A cell where several points tie at the N-th distance is left to the full-row path,
      whose sort decides which of them count, as it always did.
    """
    n = px.size
    summer = _PairwiseSum.for_length(n)
    if summer is None:
        return False
    height, width = surface.shape
    tiles = [(r0, c0) for r0 in range(0, height, TILE) for c0 in range(0, width, TILE)]
    leftovers: list[tuple[np.ndarray, np.ndarray]] = []   # (rows, cols) left to the full-row path

    def tile(origin: tuple[int, int]) -> None:
        r0, c0 = origin
        r1, c1 = min(height, r0 + TILE), min(width, c0 + TILE)
        tx, ty = xs[c0:c1], ys[r0:r1]
        # each point's nearest and farthest distance to the tile's cell centres
        left, right, top, bottom = tx[0], tx[-1], ty[0], ty[-1]
        gap_x = np.maximum(np.maximum(left - px, px - right), 0.0)
        gap_y = np.maximum(np.maximum(bottom - py, py - top), 0.0)
        near = np.sqrt(gap_x * gap_x + gap_y * gap_y)
        far_x = np.maximum(np.abs(px - left), np.abs(px - right))
        far_y = np.maximum(np.abs(py - bottom), np.abs(py - top))
        far = np.sqrt(far_x * far_x + far_y * far_y)
        reach = np.partition(far, neighbours - 1)[neighbours - 1]   # every cell has N points this close
        reach = max(reach, 1e-12) * (1 + 1e-9) + 1e-12             # rounding margin; points on the cell
        candidates = np.nonzero(near <= reach)[0]                   # ascending: the row's own order
        grid_r, grid_c = np.meshgrid(np.arange(r0, r1), np.arange(c0, c1), indexing="ij")
        rows, cols = grid_r.ravel(), grid_c.ravel()
        dx = xs[cols][:, None] - px[candidates][None, :]
        dy = ys[rows][:, None] - py[candidates][None, :]
        dist = np.sqrt(dx * dx + dy * dy)
        out = np.full(rows.size, np.nan)

        exact = dist <= 1e-12
        on_point = exact.any(axis=1)
        if on_point.any():
            out[on_point] = pz[candidates[np.argmax(exact[on_point], axis=1)]]  # lowest index, as before
        todo = np.nonzero(~on_point)[0]
        if todo.size:
            d = dist[todo]
            if radius > 0:
                d = np.where(d <= radius, d, np.inf)
            part = np.argpartition(d, neighbours - 1, axis=1)[:, :neighbours]
            nearest = np.take_along_axis(d, part, axis=1)
            kth = nearest.max(axis=1)
            tied = np.isfinite(kth) & ((d <= kth[:, None]).sum(axis=1) > neighbours)
            clear = ~tied
            weights = 1.0 / np.power(nearest[clear], power)
            weights[~np.isfinite(weights)] = 0.0
            positions = candidates[part[clear]]
            order = np.argsort(positions, axis=1)                       # the row's own order
            positions = np.take_along_axis(positions, order, axis=1)
            weights = np.take_along_axis(weights, order, axis=1)
            total, weighted = summer.sum(positions, np.stack([weights, weights * pz[positions]], axis=-1)).T
            estimate = np.where(total > 0, weighted / np.where(total > 0, total, 1.0), np.nan)
            out[todo[clear]] = estimate
            if tied.any():
                leftovers.append((rows[todo[tied]], cols[todo[tied]]))
        surface[rows, cols] = out

    workers = min(len(tiles), os.cpu_count() or 1)
    if workers <= 1:
        for origin in tiles:
            tile(origin)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(tile, tiles))
    for rows, cols in leftovers:   # ties at the N-th distance: the full row, exactly as before
        dx = xs[cols][:, None] - px[None, :]
        dy = ys[rows][:, None] - py[None, :]
        surface[rows, cols] = _estimate_row(np.sqrt(dx * dx + dy * dy), pz, power, neighbours, radius)
    return True


class _PairwiseSum:
    """numpy's sum of a row that is zero except at a few places, without the zeros.

    numpy adds a row in chunks of its buffer size (``np.getbufsize()``), each chunk by
    pairwise summation (8 running sums for runs of up to 128, halves above that), and the
    chunk sums in order. Adding a zero changes nothing, so the same grouping applied to the
    non-zero entries alone gives the same number, rounding included. Whether that model is
    numpy's on this machine is checked against ``ndarray.sum`` before it is used."""

    _checked: dict[int, "_PairwiseSum | None"] = {}

    def __init__(self, n: int):
        self.n = n
        self.chunk = max(1, int(np.getbufsize()))
        self._layouts: dict[int, tuple] = {}

    @classmethod
    def for_length(cls, n: int) -> "_PairwiseSum | None":
        """The summer for rows of ``n``, or None if it does not match numpy exactly."""
        key = (n, int(np.getbufsize()))
        if key not in cls._checked:
            summer = cls(n)
            cls._checked[key] = summer if summer._agrees_with_numpy() else None
        return cls._checked[key]

    def _agrees_with_numpy(self) -> bool:
        rng = np.random.default_rng(12345)
        rows, k = 48, min(self.n, 24)
        for trial in range(3):
            positions = np.sort(np.stack([rng.choice(self.n, k, replace=False) for _ in range(rows)]), axis=1)
            values = rng.random((rows, k)) * 10.0 ** rng.uniform(-6, 6, (rows, k))
            if trial == 2:
                values[:, ::3] *= -1.0
            full = np.zeros((rows, self.n))
            np.put_along_axis(full, positions, values, axis=1)
            both = np.stack([values, values * 0.37], axis=-1)
            if not np.array_equal(self.sum(positions, both), np.stack([full.sum(axis=1), (full * 0.37).sum(axis=1)], -1)):
                return False
        return True

    def sum(self, positions: np.ndarray, values: np.ndarray) -> np.ndarray:
        """Each row's sum, as ``row.sum()`` of the full row (zeros elsewhere) would give it.
        ``positions`` (cells, k) are ascending along each row; ``values`` is (cells, k, m):
        m sums at once, each (cells, m)."""
        cells = positions.shape[0]
        result = np.zeros((cells, values.shape[2]))
        chunk_of = positions // self.chunk
        for chunk in np.unique(chunk_of):
            start = int(chunk) * self.chunk
            length = min(self.chunk, self.n - start)
            inside = chunk_of == chunk
            result += self._pairwise(positions - start, values, inside, length)
        return result

    # ---- one chunk
    def _layout(self, length: int) -> tuple:
        """The leaves (start, size) of numpy's pairwise split of ``length``, and the order to
        add them back up: a list of (left, right) node pairs, leaves first."""
        if length not in self._layouts:
            leaves: list[tuple[int, int]] = []
            merges: list[tuple[int, int]] = []

            def split(start: int, size: int) -> int:
                if size <= 128:
                    leaves.append((start, size))
                    return -len(leaves)         # leaves are numbered -1, -2, ...
                half = size // 2
                half -= half % 8
                left = split(start, half)
                right = split(start + half, size - half)
                merges.append((left, right))
                return len(merges) - 1

            root = split(0, length)
            # nodes: leaves first (leaf i is node i), then merges; each merge goes in the
            # first level after both its children are ready
            count = len(leaves)

            def node(ref: int) -> int:
                return -ref - 1 if ref < 0 else count + ref

            level_of: list[int] = []
            levels: list[list[tuple[int, int, int]]] = []
            for index, (left, right) in enumerate(merges):
                depth = 1 + max(level_of[left] if left >= 0 else -1, level_of[right] if right >= 0 else -1)
                level_of.append(depth)
                while len(levels) <= depth:
                    levels.append([])
                levels[depth].append((count + index, node(left), node(right)))
            self._layouts[length] = (np.array([s for s, _ in leaves]), np.array([z for _, z in leaves]),
                                     merges, root)
        return self._layouts[length]

    def _pairwise(self, local: np.ndarray, values: np.ndarray, inside: np.ndarray, length: int) -> np.ndarray:
        """numpy's pairwise sum of one chunk. Only the leaves holding some value are worked
        out: an empty part of the split sums to exactly 0, and x + 0 is exactly x, so a merge
        with one empty side just passes the other side up."""
        starts, sizes, merges, root = self._layout(length)
        cells, k = local.shape
        m = values.shape[2]
        leaf = np.searchsorted(starts, np.where(inside, local, 0), side="right") - 1
        offset = local - starts[leaf]
        size = sizes[leaf]
        unrolled = (size >= 8) & (offset < size - size % 8)      # into one of the 8 running sums
        used = np.unique(leaf[inside])                             # the leaves with any value
        slot = np.zeros(len(starts), dtype=np.intp)
        slot[used] = np.arange(used.size)
        count = used.size
        compact = slot[leaf]
        row = np.arange(cells)[:, None]
        # np.add.at adds repeated places one after another in the order given, which is row by
        # row and, along a row, by ascending position: the order numpy's own loop adds them in.
        use = inside & unrolled
        accum = np.zeros((cells * count * 8, m))
        np.add.at(accum, ((row * count + compact) * 8 + offset % 8)[use], values[use])
        a = accum.reshape(cells, count, 8, m)
        leaf_sum = ((a[:, :, 0] + a[:, :, 1]) + (a[:, :, 2] + a[:, :, 3])) \
            + ((a[:, :, 4] + a[:, :, 5]) + (a[:, :, 6] + a[:, :, 7]))
        use = inside & ~unrolled                                   # the rest, one by one after
        flat = leaf_sum.reshape(cells * count, m)
        np.add.at(flat, (row * count + compact)[use], values[use])
        leaf_sum = flat.reshape(cells, count, m)
        if not merges:
            return leaf_sum[:, 0] if count else np.zeros((cells, m))
        present = set(int(x) for x in used)
        nodes: list = [None] * len(merges)

        def value(ref: int):
            if ref < 0:
                index = -ref - 1
                return leaf_sum[:, slot[index]] if index in present else None
            return nodes[ref]

        for index, (left, right) in enumerate(merges):           # children before parents
            a_, b_ = value(left), value(right)
            nodes[index] = a_ + b_ if (a_ is not None and b_ is not None) else (a_ if b_ is None else b_)
        result = value(root)
        return np.zeros((cells, m)) if result is None else result
