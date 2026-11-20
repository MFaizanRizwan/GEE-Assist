"""The analysis map: a raster canvas with a distance scale bar, a floating legend and
zoom controls laid over it. Used by both the classical and modern Analysis layouts."""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from frontend.widgets.map_overlays import LegendOverlay, ScaleBar
from frontend.widgets.raster_canvas import RasterCanvas

_ZOOM_STYLE_LIGHT = """
QPushButton#ZoomButton {
    background: rgba(255,255,255,0.92); color: #1C2B26; border: 1px solid #D8DED9;
    font-size: 15pt; font-weight: 600; padding: 0;
}
QPushButton#ZoomButton:hover { background: #FFFFFF; }
"""
_ZOOM_STYLE_DARK = """
QPushButton#ZoomButton {
    background: rgba(20,30,26,0.85); color: #E7EEEA; border: 1px solid #2A3A32;
    font-size: 15pt; font-weight: 600; padding: 0;
}
QPushButton#ZoomButton:hover { background: rgba(40,56,48,0.95); }
"""


class MapArea(QWidget):
    """A raster canvas with a scale bar, legend overlay and +/−/fit zoom buttons on top."""

    def __init__(self, dark: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._dark = dark
        self._bounds: tuple[float, float, float, float] | None = None
        self._image_width = 0

        self.canvas = RasterCanvas()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self.scalebar = ScaleBar(dark, self)
        self.legend = LegendOverlay(dark, self)

        self._zoom_buttons = []
        self._zoom_box = QWidget(self)
        zoom_layout = QVBoxLayout(self._zoom_box)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(6)
        for text, slot in (("+", lambda: self.canvas.zoom_by(1.25)),
                           ("−", lambda: self.canvas.zoom_by(1 / 1.25)),
                           ("⛶", self.canvas.fit)):
            button = QPushButton(text, objectName="ZoomButton")
            button.setFixedSize(34, 34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            zoom_layout.addWidget(button)
            self._zoom_buttons.append(button)
        self._zoom_box.setStyleSheet(_ZOOM_STYLE_DARK if dark else _ZOOM_STYLE_LIGHT)
        self._round_zoom_corners()

        self.canvas.view_changed.connect(self._update_scalebar)

    def _round_zoom_corners(self) -> None:
        for index, button in enumerate(self._zoom_buttons):
            radius = ""
            if index == 0:
                radius = "border-top-left-radius: 8px; border-top-right-radius: 8px;"
            elif index == len(self._zoom_buttons) - 1:
                radius = "border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;"
            button.setStyleSheet(f"#ZoomButton {{ {radius} }}")

    # ------------------------------------------------------------- content
    def set_image(self, image: QImage, bounds: tuple[float, float, float, float], image_width: int,
                  keep_view: bool = True) -> None:
        self._bounds = bounds
        self._image_width = image_width or image.width()
        self.canvas.set_image(image, keep_view=keep_view)
        self._update_scalebar()

    def set_opacity(self, opacity: float) -> None:
        self.canvas.set_opacity(opacity)

    def clear(self) -> None:
        self.canvas.clear()
        self.scalebar.set_metres_per_pixel(0.0)
        self.legend.hide()

    # ------------------------------------------------------------- scale bar
    def _ground_width_metres(self) -> float:
        if self._bounds is None:
            return 0.0
        west, south, east, north = self._bounds
        mid_lat = math.radians((south + north) / 2)
        return abs(east - west) * 111_320.0 * max(math.cos(mid_lat), 0.01)

    def _update_scalebar(self) -> None:
        width_m = self._ground_width_metres()
        on_screen = self._image_width * self.canvas.displayed_pixel_size()
        if width_m > 0 and on_screen > 1:
            self.scalebar.set_metres_per_pixel(width_m / on_screen)
        else:
            self.scalebar.set_metres_per_pixel(0.0)

    # ------------------------------------------------------------- layout
    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        margin = 12
        self._zoom_box.adjustSize()
        self._zoom_box.move(self.width() - self._zoom_box.width() - margin, margin)
        self.scalebar.adjustSize()
        self.scalebar.move(self.width() - self.scalebar.width() - margin,
                           self.height() - self.scalebar.height() - margin)
        if self.legend.isVisible():
            self.legend.adjustSize()
            self.legend.move(margin, self.height() - self.legend.height() - margin)

    def _reposition_legend(self) -> None:
        self.legend.adjustSize()
        self.legend.move(12, self.height() - self.legend.height() - 12)
        self.legend.raise_()

    def show_legend_classes(self, title: str, rows: list[tuple[str, str]]) -> None:
        self.legend.show_classes(title, rows)
        self._reposition_legend()

    def show_legend_scale(self, title: str, colours: tuple[str, ...], low: float, high: float) -> None:
        self.legend.show_scale(title, colours, low, (low + high) / 2, high)
        self._reposition_legend()
