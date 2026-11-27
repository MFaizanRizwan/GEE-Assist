"""The analysis map: a raster canvas with a distance scale bar, a floating legend, the
value under the pointer and zoom / full-screen controls laid over it. Used by the
Analysis and Explanation pages.

The value under the pointer comes from a *probe* the page gives (``set_value_probe``):
it turns an image pixel into the value there (an index value, or a class name).
"""

from __future__ import annotations

import math
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QKeySequence, QShortcut
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from frontend import theming
from frontend.widgets.map_overlays import LegendOverlay, ScaleBar, ValueReadout
from frontend.widgets.probe_cursor import probe_cursor
from frontend.widgets.raster_canvas import RasterCanvas

# image pixel (x, y) -> (the value there as text, what it is), or None (no value there)
ValueProbe = Callable[[int, int], "tuple[str, str] | None"]

_ZOOM_STYLE_LIGHT = """
QPushButton#ZoomButton {
    background: rgba(255,255,255,0.92); color: #1C2B26; border: 1px solid #D8DED9;
    font-size: 16.2pt; font-weight: 600; padding: 0;
}
QPushButton#ZoomButton:hover { background: #FFFFFF; }
"""
_ZOOM_STYLE_DARK = """
QPushButton#ZoomButton {
    background: rgba(20,30,26,0.85); color: #E7EEEA; border: 1px solid #2A3A32;
    font-size: 16.2pt; font-weight: 600; padding: 0;
}
QPushButton#ZoomButton:hover { background: rgba(40,56,48,0.95); }
"""


class MapArea(QWidget):
    """A raster canvas with a scale bar, legend, value readout and +/−/fit/full-screen buttons on top.

    ``full_screen`` makes the copy shown in the full-screen window: its corner button
    closes that window instead of opening another."""

    def __init__(self, dark: bool = False, parent: QWidget | None = None, full_screen: bool = False):
        super().__init__(parent)
        self._dark = dark
        self._is_full_screen_copy = full_screen
        self._bounds: tuple[float, float, float, float] | None = None
        self._image_width = 0
        self._probe: ValueProbe | None = None
        self._legend_call: tuple | None = None    # the last legend shown, to repeat in full screen
        self.full_window: QWidget | None = None   # the full-screen window, while it is open

        self.canvas = RasterCanvas()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self.scalebar = ScaleBar(dark, self)
        self.legend = LegendOverlay(dark, self)
        self.readout = ValueReadout(dark, self)

        self._zoom_buttons = []
        self._zoom_box = QWidget(self)
        zoom_layout = QVBoxLayout(self._zoom_box)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(6)
        corner = ("exit", "Exit full screen (Esc)") if full_screen else ("full", "Show the map full screen")
        for text, slot, icon, tip in (
            ("+", lambda: self.canvas.zoom_by(1.25), "", "Zoom in"),
            ("−", lambda: self.canvas.zoom_by(1 / 1.25), "", "Zoom out"),
            ("", self.canvas.fit, "fit", "Fit the whole map in view (or double-click the map)"),
            ("", self._corner_clicked, *corner),
        ):
            if icon:
                button = _IconButton(icon, objectName="ZoomButton")
            else:
                button = QPushButton(text, objectName="ZoomButton")
            button.setToolTip(tip)
            button.setFixedSize(34, 34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            zoom_layout.addWidget(button)
            self._zoom_buttons.append(button)
        self._zoom_box.setStyleSheet(_ZOOM_STYLE_DARK if dark else _ZOOM_STYLE_LIGHT)
        self._round_zoom_corners()

        self.full_button = self._zoom_buttons[-1]
        self.fit_button = self._zoom_buttons[-2]

        self.canvas.view_changed.connect(self._update_scalebar)
        self.canvas.hovered.connect(self._on_hovered)
        theming.on_theme_changed(self._refresh_cursor)   # the ring takes the new theme's colour
        self.canvas.left_image.connect(self.readout.hide)

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
        self.readout.hide()
        self._legend_call = None

    # ------------------------------------------------------------- value under the pointer
    def set_value_probe(self, probe: ValueProbe | None) -> None:
        """Show the value under the pointer, read by ``probe`` (None: show nothing). While
        there is one, the pointer over the map is a hollow ring in the theme's colour."""
        self._probe = probe
        self.readout.hide()
        self._refresh_cursor()

    def _refresh_cursor(self) -> None:
        self.canvas.set_hover_cursor(probe_cursor(self.devicePixelRatioF()) if self._probe is not None else None)

    def lon_lat_at(self, x: float, y: float) -> tuple[float, float] | None:
        """Longitude and latitude at image position (x, y) (fractional: the pointer's own
        spot, not its pixel's centre). Exact for EPSG:4326 results."""
        size = self.canvas.image_size()
        if self._bounds is None or size.isEmpty():
            return None
        west, south, east, north = self._bounds
        return (west + x / size.width() * (east - west),
                north - y / size.height() * (north - south))

    def _on_hovered(self, x: float, y: float) -> None:
        place = self.lon_lat_at(x, y)
        reading = self._probe(int(x), int(y)) if self._probe is not None else None
        if reading is None or place is None:
            self.readout.hide()
            return
        self.readout.show_value(reading[0], reading[1], *place)
        self.readout.move(12, 12)

    # ------------------------------------------------------------- full screen
    def _corner_clicked(self) -> None:
        if self._is_full_screen_copy:
            self.window().close()
        else:
            self.open_full_screen()

    def open_full_screen(self) -> QWidget | None:
        """Show this map full screen: the same picture, legend, opacity and value readout.

        A copy in a window of its own (Esc or the corner button closes it), so the page's
        layout is never disturbed."""
        if not self.canvas.has_image():
            return None
        if self.full_window is not None:
            self.full_window.close()
        window = _FullScreenWindow()
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.setWindowTitle(self.window().windowTitle() or "Map")
        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        copy = MapArea(self._dark, window, full_screen=True)
        layout.addWidget(copy)
        copy.set_image(self.canvas.image(), self._bounds or (0.0, 0.0, 0.0, 0.0), self._image_width,
                       keep_view=False)
        copy.set_opacity(self.canvas.opacity())
        copy.set_value_probe(self._probe)
        if self._legend_call is not None:
            kind, args = self._legend_call
            (copy.show_legend_scale if kind == "scale" else copy.show_legend_classes)(*args)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), window, window.close)
        window.destroyed.connect(self._full_window_closed)
        self.full_window = window
        window.showFullScreen()
        copy.canvas.fit()
        return window

    def _full_window_closed(self, *_args) -> None:
        self.full_window = None

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
        self._legend_call = ("classes", (title, rows))
        self.legend.show_classes(title, rows)
        self._reposition_legend()

    def show_legend_scale(self, title: str, colours: tuple[str, ...], low: float, high: float,
                          meaning: tuple[str, str] | None = None) -> None:
        """A colour bar; ``meaning`` says what its low and high ends are (see layer_meaning)."""
        self._legend_call = ("scale", (title, colours, low, high, meaning))
        self.legend.show_scale(title, colours, low, (low + high) / 2, high, meaning)
        self._reposition_legend()


class _FullScreenWindow(QWidget):
    """The window of a full-screen map: Esc closes it, wherever the focus is inside it."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.Window)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class _IconButton(QPushButton):
    """A map button with a drawn icon (crisp at any scale, unlike a font glyph):

    * ``fit``  - a frame with a dot: fit the whole map in view;
    * ``full`` - four corners pointing out: full screen;
    * ``exit`` - four corners pointing in: leave full screen."""

    def __init__(self, icon: str, **qt_properties):
        super().__init__("", **qt_properties)
        self.icon_kind = icon

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)
        from PyQt6.QtCore import QPointF, QRectF
        from PyQt6.QtGui import QPainter, QPalette, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = self.palette().color(QPalette.ColorRole.ButtonText)
        painter.setPen(QPen(colour, 1.6))
        box = QRectF(self.rect()).adjusted(10.5, 10.5, -10.5, -10.5)
        arm = 4.5
        if self.icon_kind == "fit":
            painter.drawRoundedRect(box.adjusted(0.5, 1.5, -0.5, -1.5), 2, 2)
            painter.setBrush(colour)
            painter.drawEllipse(box.center(), 1.6, 1.6)
        else:
            inward = self.icon_kind == "exit"
            for x, y, dx, dy in ((box.left(), box.top(), 1, 1), (box.right(), box.top(), -1, 1),
                                 (box.left(), box.bottom(), 1, -1), (box.right(), box.bottom(), -1, -1)):
                if inward:  # the corner sits inside the box, its arms pointing back out
                    x, y, dx, dy = x + dx * arm, y + dy * arm, -dx, -dy
                painter.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
                painter.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
        painter.end()
