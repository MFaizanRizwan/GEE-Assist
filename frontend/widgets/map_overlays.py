"""Overlays drawn on top of the analysis map: a distance scale bar and a floating legend.

The scale bar turns the map's current on-screen zoom into a round ground distance;
the legend floats at the bottom-left, as a colour bar (continuous layers) or a list of
class swatches (land cover). Both work in the light (classical) and dark (modern) UIs.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


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
        self._content: QWidget | None = None   # the bar + range, or the class list
        self.hide()

    def _new_content(self) -> QWidget:
        """Replace the legend's body with a fresh, empty container.

        The old body is hidden at once (``deleteLater`` alone leaves it painted and sized in
        until the event loop runs). The new one is filled by the caller and shown in
        ``_finish`` before measuring: Qt only shows a widget added to an already-visible
        parent later, so measuring it straight away shrank the legend to a clipped stub
        whenever the symbology changed."""
        if self._content is not None:
            self._content.hide()
            self._layout.removeWidget(self._content)
            self._content.deleteLater()
        self._content = QWidget(self)
        self._content.setStyleSheet("background: transparent;")
        return self._content

    def _finish(self, visible: bool) -> None:
        self._layout.addWidget(self._content)
        self._content.show()
        self._layout.activate()
        self.setVisible(visible)
        self.adjustSize()

    def show_classes(self, title: str, rows: list[tuple[str, str]]) -> None:
        self._title.setText(title.upper())
        grid = QGridLayout(self._new_content())
        grid.setContentsMargins(0, 0, 0, 0)
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
        self._finish(bool(rows))

    def show_scale(self, title: str, colours: tuple[str, ...], low: float, mid: float, high: float,
                   meaning: tuple[str, str] | None = None) -> None:
        """A colour bar from ``low`` to ``high``; with ``meaning`` (what low and high values
        mean, e.g. "Bare ground / water" and "Dense, healthy vegetation"), a swatch of each
        end's colour beside its meaning, so the legend says what the colours are."""
        self._title.setText(title.upper())
        body = QVBoxLayout(self._new_content())
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)
        bar = _OverlayColourBar(colours, self._dark)
        body.addWidget(bar)
        ends = QHBoxLayout()
        for value, align in ((low, Qt.AlignmentFlag.AlignLeft), (mid, Qt.AlignmentFlag.AlignHCenter),
                             (high, Qt.AlignmentFlag.AlignRight)):
            label = QLabel(_format_number(value))
            label.setStyleSheet(f"color: {self._ink}; font-size: 8pt;")
            label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            ends.addWidget(label, 1)
        body.addLayout(ends)
        if meaning and colours:
            means = QGridLayout()
            means.setContentsMargins(0, 2, 0, 0)
            means.setHorizontalSpacing(7)
            means.setVerticalSpacing(3)
            # high first: it reads like the bar's right end, then its left
            for row, (colour, text, arrow) in enumerate(((colours[-1], meaning[1], "High"),
                                                         (colours[0], meaning[0], "Low"))):
                swatch = QLabel()
                swatch.setFixedSize(11, 11)
                swatch.setStyleSheet(f"background: {colour}; border-radius: 2px;")
                label = QLabel(f"<span style='color:{self._muted}'>{arrow}</span>&nbsp; {text}")
                label.setStyleSheet(f"color: {self._ink}; font-size: 8.5pt;")
                means.addWidget(swatch, row, 0)
                means.addWidget(label, row, 1)
            means.setColumnStretch(1, 1)
            body.addLayout(means)
        self._finish(True)


class ValueReadout(QFrame):
    """The value under the pointer, floating over a map: the value (or class) in bold with
    what it is, and the place under the pointer. Hidden while the pointer is off the map."""

    def __init__(self, dark: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ValueReadout")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)  # never blocks the map
        bg = "rgba(14, 22, 19, 0.86)" if dark else "rgba(255, 255, 255, 0.94)"
        border = "#2A3A32" if dark else "#D8DED9"
        self._ink = "#E7EEEA" if dark else "#1C2B26"
        self._muted = "#93A79D" if dark else "#5A6B63"
        self.setStyleSheet(
            f"#ValueReadout {{ background: {bg}; border: 1px solid {border}; border-radius: 9px; }}"
            f"#ValueReadout QLabel {{ background: transparent; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 7, 12, 8)
        layout.setSpacing(1)
        self.value = QLabel()
        self.value.setStyleSheet(f"color: {self._ink}; font-size: 10.5pt;")
        self.place = QLabel()
        self.place.setStyleSheet(f"color: {self._muted}; font-size: 8pt;")
        layout.addWidget(self.value)
        layout.addWidget(self.place)
        self.hide()

    def show_value(self, value: str, what: str, lon: float, lat: float) -> None:
        """e.g. value "0.421", what "NDVI": shows **0.421** NDVI, then 31.42710° N, 73.09210° E."""
        what_html = f"&nbsp; <span style='color:{self._muted}; font-size:8.5pt'>{_escape(what)}</span>" if what else ""
        self.value.setText(f"<b>{_escape(value)}</b>{what_html}")
        self.place.setText(_place(lon, lat))
        self.adjustSize()
        self.show()
        self.raise_()

    def text(self) -> str:
        """What it shows, as plain text (for tests)."""
        return f"{self.value.text()} | {self.place.text()}"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _place(lon: float, lat: float) -> str:
    return f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'},  {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"


class _OverlayColourBar(QWidget):
    def __init__(self, colours: tuple[str, ...], dark: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._colours = colours or ("#000000", "#FFFFFF")
        self._dark = dark
        # Fill the legend's width so the low / mid / high labels line up with the bar's ends
        # (a long layer title no longer leaves the labels floating past the bar).
        self.setFixedHeight(12)
        self.setMinimumWidth(168)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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
