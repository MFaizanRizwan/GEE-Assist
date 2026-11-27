"""A result layer's value at a point of its preview, for the value under the pointer."""

from __future__ import annotations

import numpy as np

from backend.dto.map_dto import MapLayerDTO
from frontend.widgets.raster_legend import format_value


def layer_value(layer: MapLayerDTO | None, x: int, y: int,
                rows: list[tuple[str, str]] | None = None) -> tuple[str, str] | None:
    """A result layer's value at preview pixel (x, y), as (value, what it is), or None off it.

    A continuous layer reads its own values ("0.421", "NDVI"); a class layer finds the
    class whose colour the pixel was drawn in ("Trees", "Land cover"). ``rows`` are the
    classes the legend shows: a class the user hid reads as nothing.
    """
    if layer is None or not (0 <= x < layer.width and 0 <= y < layer.height):
        return None
    if layer.kind == "scale" and layer.values is not None:
        values = layer.values
        if not (y < values.shape[0] and x < values.shape[1]):
            return None
        value = float(values[y, x])
        if not np.isfinite(value):
            return ("no data", layer.name)
        return (format_value(value), layer.legend.title or layer.name)
    data = layer.data
    if data is None or not (y < data.shape[0] and x < data.shape[1]):
        return None
    red, green, blue, alpha = (int(c) for c in data[y, x])
    if alpha == 0:
        return ("no data", layer.name)
    shown = {label for label, _colour in rows} if rows is not None else None
    for label, colour, _fraction in layer.class_fractions:
        code = colour.lstrip("#")
        if len(code) >= 6 and (int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16)) == (red, green, blue):
            if shown is not None and label not in shown:
                return None
            return (label, layer.legend.title or layer.name)
    return None


def layer_value_at(layer: MapLayerDTO, lon: float, lat: float,
                   rows: list[tuple[str, str]] | None = None) -> tuple[str, str] | None:
    """``layer_value`` at a longitude and latitude (inside the layer's bounds)."""
    west, south, east, north = layer.bounds
    if east <= west or north <= south or not (west <= lon <= east and south <= lat <= north):
        return None
    x = min(int((lon - west) / (east - west) * layer.width), layer.width - 1)
    y = min(int((north - lat) / (north - south) * layer.height), layer.height - 1)
    return layer_value(layer, x, y, rows)
