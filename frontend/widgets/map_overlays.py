"""Overlays drawn on top of the analysis map: a distance scale bar and a floating legend.

The scale bar turns the map's current on-screen zoom into a round ground distance;
the legend floats at the bottom-left, as a colour bar (continuous layers) or a list of
class swatches (land cover). Both work in the light (classical) and dark (modern) UIs.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget


def _nice_distance(metres: float) -> float:
    """The largest 1/2/5 × 10ⁿ distance not longer than ``metres``."""
    if metres <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(metres))
    for step in (5, 2, 1):
        if step * power <= metres:
            return step * power
    return power


def _format_distance(metres: float) -> str:
    if metres >= 1000:
        km = metres / 1000
        return f"{km:g} km"
    return f"{metres:g} m"


class ScaleBar(QWidget):
    """A distance scale bar; give it the ground metres one screen pixel covers."""

    def __init__(self, dark: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._mpp = 0.0            # metres of ground per screen pixel
        self._dark = dark
        self._max_px = 150
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(30)
        self.setMinimumWidth(self._max_px + 8)

    def set_metres_per_pixel(self, mpp: float) -> None:
        self._mpp = mpp if (mpp and math.isfinite(mpp) and mpp > 0) else 0.0
        self.setVisible(self._mpp > 0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._mpp <= 0:
            return
        metres = _nice_distance(self._mpp * self._max_px)
        bar_px = int(round(metres / self._mpp))
        if bar_px <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        ink = QColor("#E7EEEA") if self._dark else QColor("#1C2B26")
        halo = QColor(0, 0, 0, 150) if self._dark else QColor(255, 255, 255, 190)
        y = self.height() - 8
        x0 = 4
        for colour, dy in ((halo, 1), (ink, 0)):  # a soft halo so it reads over any imagery
            painter.setPen(QPen(colour, 2 if dy else 4))
            painter.drawLine(x0, y + dy, x0 + bar_px, y + dy)
            painter.drawLine(x0, y - 4 + dy, x0, y + dy)
            painter.drawLine(x0 + bar_px, y - 4 + dy, x0 + bar_px, y + dy)
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(ink))
        painter.drawText(x0, y - 8, _format_distance(metres))
        painter.end()


class LegendOverlay(QFrame):
    """A floating legend: a continuous colour bar, or a list of land-cover classes."""

    def __init__(self, dark: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._dark = dark
        self.setObjectName("LegendOverlay")
        bg = "rgba(14, 22, 19, 0.82)" if dark else "rgba(255, 255, 255, 0.92)"
        border = "#2A3A32" if dark else "#D8DED9"
        self._ink = "#E7EEEA" if dark else "#1C2B26"
        self._muted = "#93A79D" if dark else "#5A6B63"
        self.setStyleSheet(
            f"#LegendOverlay {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}"
            f"#LegendOverlay QLabel {{ background: transparent; color: {self._ink}; }}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 14, 12)
        self._layout.setSpacing(6)
        self._title = QLabel()
        self._title.setStyleSheet(f"color: {self._muted}; font-size: 8pt; font-weight: 700; letter-spacing: 0.6px;")
        self._layout.addWidget(self._title)
        self._body = QVBoxLayout()
        self._body.setSpacing(5)
        self._layout.addLayout(self._body)
        self.hide()

    def _clear(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                inner = item.layout()
                while inner.count():
                    sub = inner.takeAt(0)
                    if sub.widget() is not None:
                        sub.widget().deleteLater()

    def show_classes(self, title: str, rows: list[tuple[str, str]]) -> None:
        self._title.setText(title.upper())
        self._clear()
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for row, (label, colour) in enumerate(rows):
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background: {colour}; border-radius: 2px;")
            name = QLabel(label)
            name.setStyleSheet(f"color: {self._ink}; font-size: 9pt;")
            grid.addWidget(swatch, row, 0)
            grid.addWidget(name, row, 1)
        grid.setColumnStretch(1, 1)
        self._body.addLayout(grid)
        self.setVisible(bool(rows))
        self.adjustSize()

    def show_scale(self, title: str, colours: tuple[str, ...], low: float, mid: float, high: float) -> None:
        self._title.setText(title.upper())
        self._clear()
        bar = _OverlayColourBar(colours, self._dark)
        self._body.addWidget(bar)
        ends = QHBoxLayout()
        for value, align in ((low, Qt.AlignmentFlag.AlignLeft), (mid, Qt.AlignmentFlag.AlignHCenter),
                             (high, Qt.AlignmentFlag.AlignRight)):
            label = QLabel(_format_number(value))
            label.setStyleSheet(f"color: {self._ink}; font-size: 8pt;")
            label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            ends.addWidget(label, 1)
        self._body.addLayout(ends)
        self.setVisible(True)
        self.adjustSize()


class _OverlayColourBar(QWidget):
    def __init__(self, colours: tuple[str, ...], dark: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._colours = colours or ("#000000", "#FFFFFF")
        self._dark = dark
        self.setFixedSize(168, 12)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
        last = max(1, len(self._colours) - 1)
        for index, colour in enumerate(self._colours):
            gradient.setColorAt(index / last, QColor(colour))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#2A3A32" if self._dark else "#C8CFCA"), 1))
        painter.drawRoundedRect(rect, 3, 3)
        painter.end()


def _format_number(value: float) -> str:
    if value is None:
        return ""
    magnitude = abs(value)
    if magnitude >= 1000 or value == int(value):
        return f"{value:,.0f}"
    if magnitude >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"
