"""Colouring an interpolated surface: colour ramps, value classes and their legend.

IDW is used for any measured quantity (soil pH, rainfall, temperature, groundwater depth,
pollution…), so the colours say nothing about the field itself: they show low to high.

* Ramps: the classic IDW colours of desktop GIS (yellow → orange → red) or Viridis.
* Classes: a continuous stretch, or the values cut into classes by *equal interval*,
  *quantile* (the same number of cells in each class) or *natural breaks* (Jenks: classes
  that group similar values), each class one colour with its range in the legend.
"""

from __future__ import annotations

import numpy as np

from frontend.widgets.symbology import ramp_table

CLASSIC = "classic"
VIRIDIS = "viridis"
CLASSIC_STOPS = ("#FFFFB2", "#FED976", "#FEB24C", "#FD8D3C", "#F03B20", "#BD0026")   # yellow → orange → red
VIRIDIS_STOPS = ("#440154", "#3B528B", "#21918C", "#5EC962", "#FDE725")

CONTINUOUS, EQUAL, QUANTILE, NATURAL = "continuous", "equal", "quantile", "natural"
METHODS = ((CONTINUOUS, "Continuous"), (EQUAL, "Equal interval"), (QUANTILE, "Quantile"),
           (NATURAL, "Natural breaks (Jenks)"))


def stops(ramp: str) -> tuple[str, ...]:
    return CLASSIC_STOPS if ramp == CLASSIC else VIRIDIS_STOPS


def _table(ramp: str) -> np.ndarray:
    """256 RGB colours along the ramp."""
    from frontend.widgets import symbology

    name = "_idw_classic" if ramp == CLASSIC else "Viridis"
    if name not in symbology.RAMPS:
        symbology.RAMPS[name] = CLASSIC_STOPS
    return ramp_table(name)


def breaks(values: np.ndarray, method: str, count: int) -> list[float]:
    """Class edges (count + 1 values, low to high) of the finite ``values``."""
    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return [0.0, 1.0]
    low, high = float(finite.min()), float(finite.max())
    count = max(2, min(12, int(count)))
    if high <= low:
        return [low, low + 1e-9]
    if method == QUANTILE:
        edges = list(np.quantile(finite, np.linspace(0, 1, count + 1)))
    elif method == NATURAL:
        edges = jenks(finite, count)
    else:
        edges = list(np.linspace(low, high, count + 1))
    edges[0], edges[-1] = low, high
    return sorted({float(e) for e in edges})   # tied quantiles merge: fewer, never empty, classes


def jenks(values: np.ndarray, count: int, sample: int = 2000) -> list[float]:
    """Natural breaks (Fisher–Jenks): classes with the least variance inside them. Run on a
    sorted sample of at most ``sample`` values (the exact method is quadratic)."""
    data = np.sort(values)
    if data.size > sample:
        data = data[np.linspace(0, data.size - 1, sample).astype(int)]
    n = data.size
    count = min(count, n)
    prefix = np.concatenate([[0.0], np.cumsum(data)])
    prefix2 = np.concatenate([[0.0], np.cumsum(data * data)])

    def cost(i: np.ndarray, j: int) -> np.ndarray:   # variance sum of data[i..j] (inclusive), i an array
        size = j - i + 1
        total = prefix[j + 1] - prefix[i]
        return (prefix2[j + 1] - prefix2[i]) - total * total / size

    best = np.full((count + 1, n), np.inf)
    back = np.zeros((count + 1, n), dtype=int)
    best[1] = np.array([cost(np.array([0]), j)[0] for j in range(n)])   # one class: data[0..j]
    for k in range(2, count + 1):
        for j in range(k - 1, n):
            starts = np.arange(k - 1, j + 1)              # first index of the last class
            candidates = best[k - 1][starts - 1] + cost(starts, j)
            pick = int(np.argmin(candidates))
            best[k][j] = candidates[pick]
            back[k][j] = starts[pick]
    edges = [float(data[-1])]
    j = n - 1
    for k in range(count, 1, -1):
        start = back[k][j]
        edges.append(float(data[start - 1]))
        j = start - 1
    edges.append(float(data[0]))
    return sorted(edges)


def render(values: np.ndarray, ramp: str, method: str, count: int,
           low: float | None = None, high: float | None = None):
    """(RGBA uint8 (H, W, 4), legend) for the surface. The legend is ("scale", low, high) for a
    continuous stretch, else ("classes", [(range label, colour), …]) from low to high."""
    values = np.asarray(values, dtype="float64")
    finite = np.isfinite(values)
    table = _table(ramp)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    if not finite.any():
        return rgba, ("scale", 0.0, 1.0)
    if method == CONTINUOUS:
        if low is None or high is None:
            low, high = (float(np.percentile(values[finite], p)) for p in (2, 98))
        span = (high - low) or 1e-9
        index = np.rint(np.clip((np.where(finite, values, low) - low) / span, 0, 1) * 255).astype(int)
        rgba[..., :3] = table[index]
        rgba[..., 3] = np.where(finite, 255, 0)
        return rgba, ("scale", low, high)
    edges = breaks(values[finite], method, count)
    classes = len(edges) - 1
    index = np.clip(np.searchsorted(edges, np.where(finite, values, edges[0]), side="right") - 1, 0, classes - 1)
    colours = [table[int(round(i / max(1, classes - 1) * 255))] for i in range(classes)]
    rgba[..., :3] = np.array(colours, dtype=np.uint8)[index]
    rgba[..., 3] = np.where(finite, 255, 0)
    rows = [(f"{_fmt(edges[i])} – {_fmt(edges[i + 1])}", "#%02X%02X%02X" % tuple(int(c) for c in colours[i]))
            for i in range(classes)]
    return rgba, ("classes", rows)


def _fmt(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.0f}"
    if magnitude >= 100:
        return f"{value:.1f}"
    if magnitude >= 1:
        return f"{value:.2f}"
    return f"{value:.3g}"
