"""A result laid over the world map, full screen ("Show on map").

Opens over the app (it used to send the picture to the Query Input page's map, which
left the Analysis page and buried the result under the parameter form). The map fills
the screen; a bar across the top has the result's name, its opacity and a Close
button (Esc also closes). The legend floats at the bottom-left, and the value under the
pointer at the top-right, as on the Analysis map.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from frontend.widgets.aoi_map_widget import AoiMapWidget
from frontend.widgets.map_overlays import LegendOverlay, ValueReadout

DEFAULT_OPACITY = 0.8
PROBE_DELAY_MS = 30   # read the value once the pointer rests this long (a file read for the Viewer)

# longitude, latitude -> (the value there as text, what it is), or None (nothing there)
LonLatProbe = Callable[[float, float], "tuple[str, str] | None"]


@dataclass
class MapExtras:
    """What goes with a picture on the map besides the picture itself.

    ``legend`` repeats a MapArea legend: ("scale", (title, colours, low, high, meaning))
    or ("classes", (title, rows)). ``probe`` reads the value at a longitude and latitude.
    """

    legend: tuple | None = None
    probe: LonLatProbe | None = None


_STYLE = """
QWidget#FullMap { background: #0B1210; }
QFrame#FullMapBar, QWidget#FullMapBar { background: #101A16; border-bottom: 1px solid #22312A; }
QLabel#FullMapTitle { color: #E7EEEA; font-size: 11pt; font-weight: 700; background: transparent; }
QLabel#FullMapMuted { color: #93A79D; font-size: 9pt; background: transparent; }
QSlider::groove:horizontal { height: 4px; background: #2A3A32; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #9BD25B; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: #9BD25B; }
QPushButton#FullMapClose {
    color: #E7EEEA; background: #1B2822; border: 1px solid #2A3A32; border-radius: 8px;
    padding: 6px 14px; font-weight: 600;
}
QPushButton#FullMapClose:hover { background: #24352D; }
"""


class FullMapWindow(QWidget):
    """The world map, full screen, with one picture laid over it at an adjustable opacity."""

    def __init__(self, png: bytes, bounds: tuple[float, float, float, float], title: str,
                 extras: MapExtras | None = None, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("FullMap")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(title)
        self.setStyleSheet(_STYLE)
        extras = extras or MapExtras()
        self._probe = extras.probe
        self._pointer: tuple[float, float] | None = None

        # ---- the bar: name, opacity, close
        bar = QWidget(objectName="FullMapBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.title_label = QLabel(title, objectName="FullMapTitle")
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(round(DEFAULT_OPACITY * 100))
        self.opacity.setFixedWidth(200)
        self.opacity.setCursor(Qt.CursorShape.PointingHandCursor)
        self.opacity.setToolTip("How strongly the result covers the map below it")
        self.opacity_value = QLabel(objectName="FullMapMuted")
        self.opacity_value.setMinimumWidth(36)
        self.close_button = QPushButton("Close  (Esc)", objectName="FullMapClose")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(12)
        row.addWidget(self.title_label, 1)
        row.addWidget(QLabel("Opacity", objectName="FullMapMuted"))
        row.addWidget(self.opacity)
        row.addWidget(self.opacity_value)
        row.addSpacing(8)
        row.addWidget(self.close_button)

        # ---- the map, with the legend and the value readout floating over it
        self.map = AoiMapWidget()
        self.legend = LegendOverlay(True, self.map)
        self.readout = ValueReadout(True, self.map)
        if extras.legend is not None:
            kind, args = extras.legend
            if kind == "scale":
                title_, colours, low, high, meaning = args
                self.legend.show_scale(title_, colours, low, (low + high) / 2, high, meaning)
            else:
                self.legend.show_classes(*args)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.map, 1)

        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.setInterval(PROBE_DELAY_MS)
        self._probe_timer.timeout.connect(self._read_value)

        self.opacity.valueChanged.connect(self._on_opacity)
        self.close_button.clicked.connect(self.close)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self.map.pointer_moved.connect(self._on_pointer)
        self.map.pointer_left.connect(self._on_pointer_left)

        self.map.show_image(png, bounds, title, opacity=DEFAULT_OPACITY, controls=False)
        self._on_opacity(self.opacity.value())

    # ------------------------------------------------------------- opacity
    def _on_opacity(self, value: int) -> None:
        self.opacity_value.setText(f"{value}%")
        self.map.set_image_opacity(value / 100)

    # ------------------------------------------------------------- value under the pointer
    def _on_pointer(self, lon: float, lat: float) -> None:
        self._pointer = (lon, lat)
        if self._probe is not None:
            self._probe_timer.start()

    def _on_pointer_left(self) -> None:
        self._pointer = None
        self._probe_timer.stop()
        self.readout.hide()

    def _read_value(self) -> None:
        if self._pointer is None or self._probe is None:
            return
        lon, lat = self._pointer
        try:
            reading = self._probe(lon, lat)
        except Exception:  # noqa: BLE001 - a failed read only hides the readout
            reading = None
        if reading is None:
            self.readout.hide()
            return
        self.readout.show_value(reading[0], reading[1], lon, lat)
        self._place_overlays()

    # ------------------------------------------------------------- layout
    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._place_overlays()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self._place_overlays()

    def _place_overlays(self) -> None:
        margin = 14
        if self.legend.isVisible():
            self.legend.adjustSize()
            self.legend.move(margin, self.map.height() - self.legend.height() - margin - 16)  # above attribution
            self.legend.raise_()
        if self.readout.isVisible():
            self.readout.adjustSize()
            self.readout.move(self.map.width() - self.readout.width() - margin, margin)
            self.readout.raise_()
