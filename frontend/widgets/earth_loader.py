"""A rotating-Earth loader, ported from GEE-Assist-Web (``EarthLoader``).

A shaded globe drawn in orthographic projection, so the continents curve round it and turn
out of sight behind the horizon, and a satellite on a tilted orbit that passes behind the
globe and back in front. Shown while something slow runs — generating an AI explanation,
or running an analysis.

It is painted natively with QPainter on a timer (about 30 frames a second, only while the
loader is on screen). An earlier version drew it in an embedded web page (Qt WebEngine),
whose frames only reach the window when the GUI thread is free and which cannot run
headless; painting it ourselves keeps it turning while an analysis works and makes it
testable.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from frontend import fonts, theme, theming

_LAND_PATH = (Path(__file__).resolve().parent.parent / "resources" / "earth_land_path.txt").read_text(
    encoding="utf-8"
)

SPIN_MS = 14000          # one turn of the Earth
ORBIT_MS = 4200          # one orbit of the satellite
FRAME_MS = 33            # ~30 frames a second
TILT = math.radians(18)  # the north pole leans toward the viewer
ORBIT_TILT = -16         # degrees: the orbit's slant on screen


def land_rings(path: str) -> list[list[float]]:
    """The land outline (an SVG path on a 200 × 100 equirectangular grid) as rings of
    ``[lon, lat, lon, lat, …]`` in degrees, ready to project onto the globe."""
    rings = []
    for chunk in path.replace("Z", "").split("M"):
        numbers = [float(n) for n in chunk.split()]
        if len(numbers) < 6:
            continue
        ring: list[float] = []
        for x, y in zip(numbers[0::2], numbers[1::2]):
            ring += [round(x * 1.8 - 180, 1), round(90 - y * 1.8, 1)]
        rings.append(ring)
    return rings


# Every ring's (longitude, latitude) in radians, built once.
_RINGS = [(np.radians(np.array(r[0::2])), np.radians(np.array(r[1::2]))) for r in land_rings(_LAND_PATH)]


def project(lon0_deg: float) -> list[np.ndarray]:
    """The land seen from above longitude ``lon0_deg``: per visible ring, an (n, 2) array of
    unit-disc coordinates (x right, y up). Points past the horizon are pinned to the rim, so
    a continent turning away is cut at the edge; rings wholly out of sight are left out."""
    lon0 = math.radians(lon0_deg)
    sin_t, cos_t = math.sin(TILT), math.cos(TILT)
    out = []
    for lon, lat in _RINGS:
        lam = lon - lon0
        cp, sp, cl = np.cos(lat), np.sin(lat), np.cos(lam)
        x = cp * np.sin(lam)
        y = cos_t * sp - sin_t * cp * cl
        z = sin_t * sp + cos_t * cp * cl
        front = z >= 0
        if not front.any():
            continue
        norm = np.hypot(x, y)
        norm[norm == 0] = 1.0
        x = np.where(front, x, x / norm)
        y = np.where(front, y, y / norm)
        out.append(np.column_stack((x, y)))
    return out


class GlobeWidget(QWidget):
    """The turning globe and its satellite, painted every frame while visible."""

    def __init__(self, size: int = 128, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(int(size * 1.6), int(size * 1.2))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self.update)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().hideEvent(event)
        self._timer.stop()  # no work while the loader is off screen

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.paint_frame(self._clock.elapsed())

    def paint_frame(self, ms: float, painter: QPainter | None = None) -> None:
        """Draw the frame at ``ms`` milliseconds (on this widget, or on ``painter``)."""
        own = painter is None
        if own:
            painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ocean, leaf = QColor(theme.OCEAN), QColor(theme.LEAF)
        w, h = self.width(), self.height()
        cx, cy, r = w / 2, h / 2, self._size * 0.46
        orx, ory = r * 1.42, r * 0.36
        lon0 = -(ms / SPIN_MS * 360.0) % 360.0           # the surface moves west to east
        t = (ms / ORBIT_MS) * 2 * math.pi % (2 * math.pi)  # 0..π in front of the globe, π..2π behind

        self._orbit(painter, cx, cy, orx, ory, ocean, front=False)
        if math.sin(t) < 0:
            self._satellite(painter, cx, cy, orx, ory, t, leaf)
        self._globe(painter, cx, cy, r, lon0, ocean)
        self._orbit(painter, cx, cy, orx, ory, ocean, front=True)
        if math.sin(t) >= 0:
            self._satellite(painter, cx, cy, orx, ory, t, leaf)
        if own:
            painter.end()

    # ------------------------------------------------------------------ parts
    @staticmethod
    def _orbit(painter, cx, cy, orx, ory, ocean: QColor, front: bool) -> None:
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(ORBIT_TILT)
        colour = QColor(ocean)
        colour.setAlphaF(0.75 if front else 0.35)
        pen = QPen(colour, 1)
        pen.setDashPattern([3, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Qt arcs run counter-clockwise from 3 o'clock: 0–180° is the upper (far) half.
        painter.drawArc(QRectF(-orx, -ory, 2 * orx, 2 * ory), (180 if front else 0) * 16, 180 * 16)
        painter.restore()

    @staticmethod
    def _satellite(painter, cx, cy, orx, ory, t, leaf: QColor) -> None:
        depth = math.sin(t)
        x, y = orx * math.cos(t), ory * math.sin(t)
        angle = math.radians(ORBIT_TILT)
        px = cx + x * math.cos(angle) - y * math.sin(angle)
        py = cy + x * math.sin(angle) + y * math.cos(angle)
        painter.save()
        painter.translate(px, py)
        painter.rotate(ORBIT_TILT)
        scale = 1 + 0.18 * depth                               # nearer looks bigger
        painter.scale(scale, scale)
        painter.setOpacity(0.6 if depth < 0 else 1.0)
        glow = QColor(leaf)
        glow.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), 9, 6)
        painter.setBrush(QColor("#2f5f9e"))
        painter.drawRect(QRectF(-8, -2.5, 5.5, 5))           # solar panels
        painter.drawRect(QRectF(2.5, -2.5, 5.5, 5))
        painter.setBrush(QColor("#d9ad4f"))
        painter.drawRect(QRectF(-2.5, -3.5, 5, 7))           # body
        painter.restore()

    @staticmethod
    def _globe(painter, cx, cy, r, lon0, ocean: QColor) -> None:
        centre = QPointF(cx, cy)
        for width, alpha in ((7, 0.10), (3, 0.30)):            # atmosphere
            halo = QColor(ocean)
            halo.setAlphaF(alpha)
            painter.setPen(QPen(halo, width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, r + 2.5, r + 2.5)

        sea = QRadialGradient(centre, r * 1.05, QPointF(cx - r * 0.3, cy - r * 0.4))
        sea.setColorAt(0.0, QColor("#3f8fd0"))
        sea.setColorAt(0.6, QColor("#1d5f97"))
        sea.setColorAt(1.0, QColor("#0c3559"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(sea))
        painter.drawEllipse(centre, r, r)

        disc = QPainterPath()
        disc.addEllipse(centre, r, r)
        painter.save()
        painter.setClipPath(disc)
        land = QPainterPath()
        land.setFillRule(Qt.FillRule.WindingFill)
        for ring in project(lon0):
            land.addPolygon(QPolygonF([QPointF(cx + r * x, cy - r * y) for x, y in ring]))
            land.closeSubpath()
        pen = QPen(QColor("#5aa873"), 0.6)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QColor("#7cc58f"))
        painter.drawPath(land)

        shade = QRadialGradient(centre, r, QPointF(cx - r * 0.3, cy - r * 0.38))
        shade.setColorAt(0.0, QColor(255, 255, 255, 77))
        shade.setColorAt(0.45, QColor(255, 255, 255, 0))
        shade.setColorAt(0.8, QColor(2, 12, 20, 77))
        shade.setColorAt(1.0, QColor(2, 12, 20, 166))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(shade))
        painter.drawEllipse(centre, r, r)
        painter.restore()


class EarthLoader(QWidget):
    """A turning globe with an orbiting satellite and a caption, shown while something slow runs.

    ``set_text(label, detail)`` updates the caption live. The globe animates only while the
    loader is on screen.
    """

    def __init__(self, label: str = "Working…", detail: str = "", size: int = 128,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("EarthLoader")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.globe = GlobeWidget(size)
        self.label = QLabel(label)
        self.detail = QLabel(detail)
        for caption in (self.label, self.detail):
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setWordWrap(True)
        theming.styled(self.label, lambda: (
            f"font-family: '{theme.SANS}'; font-size: {fonts.LG}pt; font-weight: 600;"
            f" color: {theme.INK}; background: transparent;"))
        theming.styled(self.detail, lambda: (
            f"font-family: '{theme.SANS}'; font-size: {fonts.MD}pt; color: {theme.MUTED}; background: transparent;"))
        self.detail.setVisible(bool(detail))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)
        layout.addStretch(1)
        layout.addWidget(self.globe, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(self.label)
        layout.addWidget(self.detail)
        layout.addStretch(1)
        theming.on_theme_changed(self._retheme)  # ocean / glow follow a live theme change

    def _retheme(self) -> None:
        self.globe.update()

    def set_text(self, label: str, detail: str = "") -> None:
        self.label.setText(label)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
