"""IDW is fast and still gives exactly the surface it always gave, bit for bit.

The reference below is the original computation, kept verbatim: one output row at a time,
every cell against every point, ``argsort`` for the nearest N, sums over the full row."""

import numpy as np
import pytest

from backend.business.interpolation import interpolation_service as idw


def _reference_row(dist, values, power, neighbours, radius):
    width = dist.shape[0]
    out = np.full(width, np.nan)
    exact = dist <= 1e-12
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
        keep = np.argsort(d, axis=1)[:, :neighbours]
        mask = np.zeros_like(weights, dtype=bool)
        np.put_along_axis(mask, keep, True, axis=1)
        weights = np.where(mask, weights, 0.0)
    weights[~np.isfinite(weights)] = 0.0
    total = weights.sum(axis=1)
    estimate = np.where(total > 0, (weights * values[None, :]).sum(axis=1) / np.where(total > 0, total, 1.0), np.nan)
    out[todo] = estimate
    return out


def _reference_surface(xs, ys, px, py, pz, power, neighbours, radius):
    surface = np.full((ys.size, xs.size), np.nan)
    for row in range(ys.size):
        dx = xs[:, None] - px[None, :]
        dy = ys[row] - py[None, :]
        surface[row] = _reference_row(np.sqrt(dx * dx + dy * dy), pz, power, neighbours, radius)
    return surface


def _points(kind, rng):
    if kind == "scattered":
        n = int(rng.integers(20, 400))
        return rng.uniform(73, 74, n), rng.uniform(31, 32, n)
    if kind == "grid":                       # many exact distance ties
        g = int(rng.integers(3, 12))
        px, py = np.meshgrid(np.linspace(73, 74, g), np.linspace(31, 32, g))
        return px.ravel(), py.ravel()
    if kind == "integer":                    # duplicates and cells on points
        n = int(rng.integers(5, 80))
        return rng.integers(0, 10, n).astype(float), rng.integers(0, 10, n).astype(float)
    n = 9000                                 # more than numpy's 8,192 summing chunk
    return rng.uniform(73, 74, n), rng.uniform(31, 32, n)


@pytest.mark.parametrize("kind", ["scattered", "grid", "integer", "many"])
@pytest.mark.parametrize("power,neighbours,radius", [(2.0, 12, 0.0), (1.7, 5, 0.0), (3.0, 7, 0.15),
                                                     (2.0, 1, 0.0), (2.0, 0, 0.0)])
def test_the_surface_is_bit_for_bit_the_original(kind, power, neighbours, radius):
    rng = np.random.default_rng(hash((kind, power, neighbours)) % 2**32)
    px, py = _points(kind, rng)
    pz = rng.normal(0, 20, px.size)
    pz[::7] = 0.0
    bounds, (cx, cy), width, height = idw._grid(px, py, 48 if kind == "many" else 70)
    xs = bounds[0] + (np.arange(width) + 0.5) * cx
    ys = bounds[3] - (np.arange(height) + 0.5) * cy
    k = neighbours if 0 < neighbours < px.size else 0
    want = _reference_surface(xs, ys, px, py, pz, power, k, radius)
    got = np.full_like(want, np.nan)
    idw._fill_surface(got, xs, ys, px, py, pz, power, k, radius)
    assert np.array_equal(want.view(np.int64), got.view(np.int64))   # every bit, NaNs and zeros included


@pytest.mark.parametrize("n", [5, 127, 128, 129, 1000, 8192, 8193, 20000])
def test_sparse_sums_are_numpys_own(n):
    summer = idw._PairwiseSum.for_length(n)
    assert summer is not None   # the model of numpy's summing holds here
    rng = np.random.default_rng(n)
    k = min(n, 15)
    positions = np.sort(np.stack([rng.choice(n, k, replace=False) for _ in range(30)]), axis=1)
    values = rng.random((30, k, 1)) * 10.0 ** rng.uniform(-8, 8, (30, k, 1))
    full = np.zeros((30, n))
    np.put_along_axis(full, positions, values[..., 0], axis=1)
    assert np.array_equal(summer.sum(positions, values)[:, 0], full.sum(axis=1))


def test_without_numpys_summing_model_the_full_rows_are_used(monkeypatch):
    """If numpy summed differently (another version), the fast path stands down."""
    monkeypatch.setattr(idw._PairwiseSum, "_agrees_with_numpy", lambda self: False)
    monkeypatch.setattr(idw._PairwiseSum, "_checked", {})
    rng = np.random.default_rng(4)
    px, py, pz = rng.uniform(73, 74, 50), rng.uniform(31, 32, 50), rng.normal(0, 1, 50)
    bounds, (cx, cy), width, height = idw._grid(px, py, 40)
    xs = bounds[0] + (np.arange(width) + 0.5) * cx
    ys = bounds[3] - (np.arange(height) + 0.5) * cy
    surface = np.full((height, width), np.nan)
    assert idw._fill_nearest_tiles(surface, xs, ys, px, py, pz, 2.0, 12, 0.0) is False
    idw._fill_surface(surface, xs, ys, px, py, pz, 2.0, 12, 0.0)
    want = _reference_surface(xs, ys, px, py, pz, 2.0, 12, 0.0)
    assert np.array_equal(want.view(np.int64), surface.view(np.int64))
