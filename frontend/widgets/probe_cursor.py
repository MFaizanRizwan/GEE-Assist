"""The pointer over a map whose values can be read: a hollow ring, in the theme's colours.

The ring's centre is the spot being read, left open so the colour under it stays visible.
It is drawn in the theme's least-used colour (``theme.least_used_colour``), so it stands
apart from the rest of the UI, with a thin halo in a contrasting shade so it shows over
any map colours, light or dark.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap

from frontend import theme

SIZE = 24            # cursor picture, logical pixels
RADIUS = 7.0         # the ring's radius
WIDTH = 2.2          # the ring's line width


def ring_colour() -> QColor:
    return QColor(theme.least_used_colour())


def halo_colour(ring: QColor) -> QColor:
    """Near-black around a light ring, white around a dark one."""
    halo = QColor("#101010") if ring.lightnessF() > 0.55 else QColor("#FFFFFF")
    halo.setAlpha(200)
    return halo


def probe_pixmap(ratio: float = 1.0) -> QPixmap:
    """The ring, at ``ratio`` device pixels per logical pixel (sharp on scaled screens)."""
    pixmap = QPixmap(round(SIZE * ratio), round(SIZE * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    ring = ring_colour()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    centre = QPointF(SIZE / 2, SIZE / 2)
    painter.setPen(QPen(halo_colour(ring), WIDTH + 2.4))   # the halo, under the ring
    painter.drawEllipse(centre, RADIUS, RADIUS)
    painter.setPen(QPen(ring, WIDTH))
    painter.drawEllipse(centre, RADIUS, RADIUS)
    painter.end()
    return pixmap


def probe_cursor(ratio: float = 1.0) -> QCursor:
    """The ring as a cursor, its hot spot at the centre."""
    return QCursor(probe_pixmap(ratio), SIZE // 2, SIZE // 2)
