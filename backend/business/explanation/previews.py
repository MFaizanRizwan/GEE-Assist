"""PNG previews of result layers for Gemini, encoded with NumPy and zlib (no imaging library needed)."""

from __future__ import annotations

import struct
import zlib

import numpy as np

from backend.dto.map_dto import LegendDTO

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def rgba_to_png(rgba) -> bytes:
    """An 8-bit RGBA image (height, width, 4) as PNG bytes."""
    pixels = np.ascontiguousarray(rgba, dtype=np.uint8)
    if pixels.ndim != 3 or pixels.shape[2] != 4:
        raise ValueError(f"Expected an RGBA image (height, width, 4), got {pixels.shape}")
    height, width = pixels.shape[:2]
    # Every row starts with filter type 0 (none).
    rows = np.concatenate([np.zeros((height, 1), np.uint8), pixels.reshape(height, width * 4)], axis=1)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8 bits, RGBA, deflate, no interlace
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + \
        _chunk(b"IEND", b"")


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def describe_legend(legend: LegendDTO | None) -> str:
    """How a preview is coloured, in words Gemini can use to read it."""
    if legend is None:
        return ""
    if legend.kind == "scale" and legend.colours:
        return (f"from {legend.colours[0]} (low) to {legend.colours[-1]} (high) "
                f"over {legend.low:g} to {legend.high:g}; transparent = no data")
    if legend.kind == "classes" and legend.labels:
        pairs = [f"{label} = {colour}" for label, colour in zip(legend.labels, legend.colours)]
        return "classes: " + ", ".join(pairs or legend.labels)
    if legend.kind == "rgb" and legend.labels:
        return "red, green, blue = " + ", ".join(legend.labels)
    return ""
