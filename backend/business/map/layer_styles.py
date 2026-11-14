"""Colour styles for analysis result layers, and drawing one band of a result as RGBA.

A style is a colour scale (``SCALES``), or one of the categorical styles:
``mask`` (0 land / 1 water), ``classes`` (land-cover classes) and ``transition``
(before × 100 + after codes: grey where unchanged, the new class's colour where changed).
"""

from __future__ import annotations

import numpy as np

from backend.business.map.colour_maps import CLASS_TABLES, GREYS, VEGETATION, VIRIDIS, WATER, ColourMap
from backend.dto.map_dto import LegendDTO

STRETCH = (2.0, 98.0)
UNCHANGED = "#D9D9D9"
LAND = "#E8E2D0"
WATER_BLUE = "#1F6FD1"

SCALES: dict[str, ColourMap] = {
    "vegetation": VEGETATION,
    "water": WATER,
    "viridis": VIRIDIS,
    "grey": GREYS,
    "diverging": ColourMap("Diverging", ((0.0, "#B2182B"), (0.25, "#EF8A62"), (0.5, "#F7F7F7"), (0.75, "#67A9CF"),
                                         (1.0, "#2166AC"))),
    "change": ColourMap("Change", ((0.0, "#2166AC"), (0.5, "#F7F7F7"), (1.0, "#B2182B"))),  # cooler -> warmer
    "dryness": ColourMap("Dryness", ((0.0, "#2C7BB6"), (0.5, "#FFFFBF"), (1.0, "#A6611A"))),
    "condition": ColourMap("Condition", ((0.0, "#A50026"), (0.35, "#F46D43"), (0.5, "#FEE08B"), (0.7, "#A6D96A"),
                                         (1.0, "#1A9850"))),
    "burn": ColourMap("Burn severity", ((0.0, "#1A9850"), (0.3, "#D9EF8B"), (0.5, "#FEE08B"), (0.7, "#F46D43"),
                                        (0.85, "#D73027"), (1.0, "#7B3294"))),
    "soil": ColourMap("Soil", ((0.0, "#F7F4E9"), (0.5, "#D8B365"), (1.0, "#8C510A"))),
    "urban": ColourMap("Urban", ((0.0, "#1B7837"), (0.45, "#F7F7F7"), (0.75, "#BDBDBD"), (1.0, "#C51B7D"))),
    "snow": ColourMap("Snow", ((0.0, "#8C510A"), (0.5, "#F6E8C3"), (0.75, "#FFFFFF"), (1.0, "#4EB3D3"))),
    "turbidity": ColourMap("Turbidity", ((0.0, "#08519C"), (0.5, "#C7E9C0"), (1.0, "#8C510A"))),
    "algae": ColourMap("Algae", ((0.0, "#08306B"), (0.5, "#41B6C4"), (1.0, "#31A354"))),
    "thermal": ColourMap("Thermal", ((0.0, "#313695"), (0.25, "#74ADD1"), (0.5, "#FFFFBF"), (0.75, "#F46D43"),
                                     (1.0, "#A50026"))),
}


def _hex_rgb(colour: str) -> list[int]:
    return [int(colour[i:i + 2], 16) for i in (1, 3, 5)]


def draw(values: np.ndarray, valid: np.ndarray, style: str, title: str, low: float | None = None,
         high: float | None = None, classes: str = "") -> tuple[np.ndarray, LegendDTO]:
    """(RGB uint8 image, legend) for one result band; ``valid`` marks pixels with data."""
    if style == "mask":
        rgb = np.zeros(values.shape + (3,), dtype=np.uint8)
        rgb[valid & (values > 0.5)] = _hex_rgb(WATER_BLUE)
        rgb[valid & (values <= 0.5)] = _hex_rgb(LAND)
        return rgb, LegendDTO("classes", title, colours=(WATER_BLUE, LAND), labels=("Water", "Land"))
    if style in ("classes", "transition"):
        return _classes(values, valid, style, title, classes)
    scale = SCALES.get(style, VIRIDIS)
    if low is None or high is None:
        low, high = _stretch(values, valid, symmetric=style == "change")
    span = high - low if high > low else 1e-9
    rgb = scale.apply((values - low) / span)
    return rgb, LegendDTO("scale", title, low=float(low), high=float(high), colours=scale.colours())


def _stretch(values: np.ndarray, valid: np.ndarray, symmetric: bool = False) -> tuple[float, float]:
    if not valid.any():
        return 0.0, 1.0
    low, high = (float(v) for v in np.percentile(values[valid], STRETCH))
    if symmetric:
        edge = max(abs(low), abs(high)) or 1.0
        return -edge, edge
    return (low, high) if high > low else (low, low + 1.0)


def _classes(values: np.ndarray, valid: np.ndarray, style: str, title: str, table: str):
    first, entries = CLASS_TABLES.get(table, CLASS_TABLES["dynamic_world"])
    palette = np.array([_hex_rgb(colour) for _, colour in entries], dtype=np.uint8)
    codes = np.where(valid, np.nan_to_num(values), -1).round().astype(np.int64)
    rgb = np.zeros(values.shape + (3,), dtype=np.uint8)
    if style == "transition":
        before, after = codes // 100, codes % 100
        unchanged = valid & (before == after)
        rgb[unchanged] = _hex_rgb(UNCHANGED)
        shown = valid & ~unchanged
        index = after - first
    else:
        shown, unchanged = valid, np.zeros_like(valid)
        index = codes - first
    known = shown & (index >= 0) & (index < len(entries))
    rgb[known] = palette[index[known]]
    present = sorted(set(np.unique(index[known]).tolist()))
    colours = tuple(entries[i][1] for i in present)
    labels = tuple(entries[i][0] for i in present)
    if style == "transition":
        colours, labels = (UNCHANGED,) + colours, ("Unchanged",) + tuple(f"→ {label}" for label in labels)
    return rgb, LegendDTO("classes", title, colours=colours, labels=labels)
