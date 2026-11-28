"""Contours are traced with numpy, all levels at once, and give exactly what the
cell-by-cell marching squares gave: the same segments in the same order, and the same
picture pixel for pixel (the reference below is that original scan, kept verbatim)."""

import math

import numpy as np
import pytest

from backend.business.terrain import terrain_service as ts


# ------------------------------------------------------------------ the original, cell by cell
def _reference_segments(z, level):
    segments = []
    h, w = z.shape
    for r in range(h - 1):
        for cidx in range(w - 1):
            tl, tr = z[r, cidx], z[r, cidx + 1]
            bl, br = z[r + 1, cidx], z[r + 1, cidx + 1]
            if not (np.isfinite(tl) and np.isfinite(tr) and np.isfinite(bl) and np.isfinite(br)):
                continue
            case = (int(tl >= level) << 3) | (int(tr >= level) << 2) | (int(br >= level) << 1) | int(bl >= level)
            if case in (0, 15):
                continue
            top = (cidx + ts._interp(tl, tr, level), r)
            right = (cidx + 1, r + ts._interp(tr, br, level))
            bottom = (cidx + ts._interp(bl, br, level), r + 1)
            left = (cidx, r + ts._interp(tl, bl, level))
            for p, q in ts._CASE_EDGES.get(case, ()):
                edges = {"T": top, "R": right, "B": bottom, "L": left}
                (x0, y0), (x1, y1) = edges[p], edges[q]
                segments.append((x0, y0, x1, y1))
    return segments


def _grids():
    rng = np.random.default_rng(5)
    for trial in range(24):
        h, w = int(rng.integers(2, 24)), int(rng.integers(2, 24))
        kind = trial % 4
        if kind == 0:
            z = rng.normal(100, 30, (h, w))
        elif kind == 1:                                   # plateaus; corners exactly on levels
            z = rng.integers(0, 6, (h, w)).astype(float) * 10
        elif kind == 2:                                   # many equal neighbours (flat edges)
            z = np.round(rng.normal(0, 3, (h, w)))
        else:
            yy, xx = np.mgrid[0:h, 0:w]
            z = np.sin(xx / 3.0) * 50 + np.cos(yy / 4.0) * 50
        if trial % 3 == 0:
            z[rng.random((h, w)) < 0.15] = np.nan         # no-data
        yield z


@pytest.mark.parametrize("z", list(_grids()))
def test_segments_are_exactly_the_cell_by_cell_ones(z):
    for level in (0.0, 10.0, 20.0, 50.0, -3.0, 2.5, 100.0):
        assert ts.contour_segments(z, level) == _reference_segments(z, level)


@pytest.mark.parametrize("z", list(_grids()))
def test_all_levels_at_once_draw_exactly_the_same_picture(z):
    if not np.isfinite(z).any():
        return
    low, high = float(np.nanmin(z)), float(np.nanmax(z))
    colour = np.array([70, 70, 70], np.uint8)
    for interval in (1.0, 5.0, 7.3):
        level, levels = math.ceil(low / interval) * interval, []
        while level < high:
            levels.append(level)
            level += interval
        want = np.zeros(z.shape + (3,), np.uint8)
        for value in levels:
            for segment in _reference_segments(z, value):
                ts._draw_line(want, *segment, colour)
        got = np.zeros_like(want)
        count = 0
        for x0, y0, x1, y1 in ts._ContourCells(z).segments_for(levels, batch=29):   # small: many batches
            ts._draw_segments(got, x0, y0, x1, y1, colour)
            count += x0.size
        assert np.array_equal(got, want)
        assert count == sum(len(_reference_segments(z, value)) for value in levels)
