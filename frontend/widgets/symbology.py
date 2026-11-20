"""Client-side colour ramps and recolouring for continuous analysis layers.

The backend hands a layer its raw values (NaN = no-data) and statistics; the
Symbology panel then recolours it live — a different ramp, inverted, a new stretch
or gamma — without re-running the analysis. No plotting library is needed.
"""

from __future__ import annotations

import numpy as np

# name -> colour stops, low to high. Chosen to match the symbology panel's palette grid.
RAMPS: dict[str, tuple[str, ...]] = {
    "Red–Yellow–Green": ("#A50026", "#D73027", "#F46D43", "#FEE08B", "#D9EF8B", "#66BD63", "#1A9850"),
    "Viridis": ("#440154", "#3B528B", "#21918C", "#5EC962", "#FDE725"),
    "Yellow–Green": ("#FFFFE5", "#D9F0A3", "#78C679", "#238443", "#004529"),
    "Magma": ("#000004", "#3B0F70", "#8C2981", "#DE4968", "#FE9F6D", "#FCFDBF"),
    "Turbo": ("#30123B", "#4064F0", "#1AE4B6", "#A4FC3B", "#FB8022", "#C2201F", "#7A0403"),
    "Spectral": ("#9E0142", "#F46D43", "#FEE08B", "#FFFFBF", "#E6F598", "#66C2A5", "#5E4FA2"),
    "Brown–Teal": ("#543005", "#BF812D", "#F6E8C3", "#C7EAE5", "#35978F", "#003C30"),
    "Blues": ("#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5", "#08306B"),
    "Blue–Red (diverging)": ("#2166AC", "#67A9CF", "#F7F7F7", "#EF8A62", "#B2182B"),
    "Greyscale": ("#000000", "#FFFFFF"),
}
DEFAULT_RAMP = "Viridis"

# Stretch presets: a key, its label, and how it picks (low, high) from the statistics.
STRETCHES: tuple[tuple[str, str], ...] = (
    ("minmax", "Min–Max"),
    ("p2_98", "2–98%"),
    ("sigma2", "±2σ"),
    ("custom", "Custom"),
)


def ramp_stops(name: str) -> tuple[str, ...]:
    return RAMPS.get(name, RAMPS[DEFAULT_RAMP])


def ramp_table(name: str, invert: bool = False, steps: int = 256) -> np.ndarray:
    """``steps`` x 3 uint8 colours from the low end to the high end of the named ramp."""
    stops = ramp_stops(name)
    positions = np.linspace(0.0, 1.0, len(stops))
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in stops], dtype=float)
    x = np.linspace(0.0, 1.0, steps)
    table = np.stack([np.interp(x, positions, rgb[:, c]) for c in range(3)], axis=1)
    table = table.round().astype(np.uint8)
    return table[::-1].copy() if invert else table


def ramp_preview_colours(name: str, invert: bool = False, count: int = 7) -> tuple[str, ...]:
    """A few evenly spaced hex colours, for a legend or a palette swatch."""
    return tuple("#%02X%02X%02X" % tuple(row) for row in ramp_table(name, invert, count))


def stretch_bounds(key: str, stats: dict) -> tuple[float, float]:
    """(low, high) for a stretch preset from a layer's statistics."""
    if not stats:
        return 0.0, 1.0
    if key == "minmax":
        lo, hi = stats["min"], stats["max"]
    elif key == "sigma2":
        lo, hi = stats["mean"] - 2 * stats["std"], stats["mean"] + 2 * stats["std"]
    else:  # p2_98 (also the Custom default)
        lo, hi = stats["p2"], stats["p98"]
    if hi <= lo:
        hi = lo + 1e-9
    return float(lo), float(hi)


# A vivid, well-separated palette for the "high contrast" class option.
HIGH_CONTRAST = (
    "#E6194B", "#3CB44B", "#4363D8", "#F58231", "#911EB4", "#42D4F4", "#F032E6", "#BFEF45",
    "#FABED4", "#469990", "#DCBEFF", "#9A6324", "#FFFAC8", "#800000", "#AAFFC3", "#808000", "#FFD8B1",
)


def high_contrast_colour(index: int) -> str:
    return HIGH_CONTRAST[index % len(HIGH_CONTRAST)]


def recolor_classes(rgba: np.ndarray, mapping: list[tuple[str, str | None]]) -> np.ndarray:
    """Remap a categorical layer's colours: ``mapping`` is (old_hex, new_hex or None=hide)."""
    out = rgba.copy()
    for old, new in mapping:
        r, g, b = (int(old[i:i + 2], 16) for i in (1, 3, 5))
        match = (rgba[..., 0] == r) & (rgba[..., 1] == g) & (rgba[..., 2] == b) & (rgba[..., 3] > 0)
        if new is None:
            out[..., 3][match] = 0
        elif new != old:
            nr, ng, nb = (int(new[i:i + 2], 16) for i in (1, 3, 5))
            out[..., 0][match], out[..., 1][match], out[..., 2][match] = nr, ng, nb
    return out


def colorize(values: np.ndarray, ramp: str, low: float, high: float,
             invert: bool = False, gamma: float = 1.0) -> np.ndarray:
    """RGBA uint8 (H, W, 4) for ``values`` (NaN = transparent) mapped through the ramp over [low, high]."""
    span = (high - low) or 1e-9
    scaled = np.clip((np.nan_to_num(values, nan=low) - low) / span, 0.0, 1.0)
    if gamma and gamma != 1.0:
        scaled = np.power(scaled, 1.0 / max(gamma, 1e-6))
    index = np.rint(scaled * 255).astype(np.int64)
    rgb = ramp_table(ramp, invert)[index]
    alpha = np.where(np.isfinite(values), 255, 0).astype(np.uint8)
    return np.dstack([rgb, alpha])
