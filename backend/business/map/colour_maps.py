"""Colour scales for single-band and index views, and the Dynamic World class colours.

A scale is a few colour stops, blended into a 256-step table; values from 0 to 1 are
looked up in it. No plotting library is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ColourMap:
    name: str
    stops: tuple[tuple[float, str], ...]   # (position 0-1, "#RRGGBB"), from low to high

    def table(self, steps: int = 256) -> np.ndarray:
        """``steps`` x 3 uint8 colours, from the low end to the high end."""
        positions = np.array([position for position, _ in self.stops])
        rgb = np.array([[int(colour[i:i + 2], 16) for i in (1, 3, 5)] for _, colour in self.stops], dtype=float)
        x = np.linspace(0.0, 1.0, steps)
        return np.stack([np.interp(x, positions, rgb[:, c]) for c in range(3)], axis=1).round().astype(np.uint8)

    def colours(self, count: int = 5) -> tuple[str, ...]:
        """``count`` evenly spaced colours from low to high (for a legend)."""
        return tuple("#%02X%02X%02X" % tuple(row) for row in self.table(count))

    def apply(self, values: np.ndarray) -> np.ndarray:
        """Colours (``values.shape`` x 3, uint8) for ``values`` from 0 to 1 (clipped)."""
        index = np.clip(np.nan_to_num(values, nan=0.0), 0.0, 1.0) * 255
        return self.table()[np.rint(index).astype(np.int64)]


VIRIDIS = ColourMap("Viridis", ((0.0, "#440154"), (0.25, "#3B528B"), (0.5, "#21918C"), (0.75, "#5EC962"),
                                (1.0, "#FDE725")))
VEGETATION = ColourMap("Vegetation", ((0.0, "#A50026"), (0.3, "#D9A441"), (0.5, "#FFFFBF"), (0.7, "#91CF60"),
                                      (1.0, "#1A7837")))   # bare / water -> dense vegetation
WATER = ColourMap("Water", ((0.0, "#F7FBFF"), (0.5, "#6BAED6"), (1.0, "#08306B")))  # dry -> open water
GREYS = ColourMap("Greys", ((0.0, "#000000"), (1.0, "#FFFFFF")))

# Dynamic World "label": class number -> (name, colour), as Google publishes them.
DYNAMIC_WORLD_CLASSES: tuple[tuple[str, str], ...] = (
    ("Water", "#419BDF"),
    ("Trees", "#397D49"),
    ("Grass", "#88B053"),
    ("Flooded vegetation", "#7A87C6"),
    ("Crops", "#E49635"),
    ("Shrub and scrub", "#DFC35A"),
    ("Built area", "#C4281B"),
    ("Bare ground", "#A59B8F"),
    ("Snow and ice", "#B39FE1"),
)

# MODIS MCD12Q1 LC_Type1 (IGBP): class number 1-17 -> (name, colour), as the GEE catalogue shows them.
MODIS_IGBP_CLASSES: tuple[tuple[str, str], ...] = (
    ("Evergreen needleleaf forest", "#05450A"),
    ("Evergreen broadleaf forest", "#086A10"),
    ("Deciduous needleleaf forest", "#54A708"),
    ("Deciduous broadleaf forest", "#78D203"),
    ("Mixed forest", "#009900"),
    ("Closed shrubland", "#C6B044"),
    ("Open shrubland", "#DCD159"),
    ("Woody savanna", "#DADE48"),
    ("Savanna", "#FBFF13"),
    ("Grassland", "#B6FF05"),
    ("Permanent wetland", "#27FF87"),
    ("Cropland", "#C24F44"),
    ("Urban and built-up", "#A5A5A5"),
    ("Cropland / natural vegetation mosaic", "#FF6D4C"),
    ("Permanent snow and ice", "#69FFF8"),
    ("Barren", "#F9FFA4"),
    ("Water", "#1C0DFF"),
)

# Class table key -> (number of the first class, classes). Dynamic World starts at 0, MODIS IGBP at 1.
CLASS_TABLES: dict[str, tuple[int, tuple[tuple[str, str], ...]]] = {
    "dynamic_world": (0, DYNAMIC_WORLD_CLASSES),
    "modis_igbp": (1, MODIS_IGBP_CLASSES),
}


def class_name(table: str, number: int) -> str:
    first, classes = CLASS_TABLES[table]
    index = number - first
    return classes[index][0] if 0 <= index < len(classes) else f"Class {number}"
