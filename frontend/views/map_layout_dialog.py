"""Design a printable map and export it as PDF (IDW and DEM pages).

A page (A4, A3 or Letter, portrait or landscape) holds the map and the map elements: a
title, a north arrow, a distance scale bar, a legend and a note. Each element can be shown
or hidden and dragged anywhere on the page; the title is edited in place (double-click it)
or in the panel. Export paints the page into a PDF: lines and text stay vector, sharp at
any zoom.

* Two layouts. "Area only": the analysed area fills the page. "Country with magnified
  area": a locator map of the whole boundary layer (e.g. the country) with the analysed
  area boxed, and beside it the area magnified, joined to its box by guide lines.
* North arrow: a library of styles (classic, compass rose, star, half arrow, …). Drag its
  corner handle to resize it, or use the size slider.
* Scale bar: drag its right end to stretch or compress it; its distances follow live. It
  measures on the map it is placed over (the locator or the magnified area).

The maps keep their true shape: a map in degrees is widened by the cosine of its latitude,
as the ground is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from frontend import theme, theming

PAGE_SIZES = {"A4": QPageSize.PageSizeId.A4, "A3": QPageSize.PageSizeId.A3, "Letter": QPageSize.PageSizeId.Letter}
MARGIN = 36.0          # page margin, points
INK = QColor("#1C2B26")
AREA_ONLY, WITH_LOCATOR = "area", "locator"
HANDLE = 7.0           # resize handle, points


@dataclass
class MapLayoutSpec:
    """What goes on the page. Coordinates (extents, rings, points) are in the raster's CRS."""

    title: str
    image: QImage
    extent: tuple[float, float, float, float]           # west, south, east, north (of the image)
    geographic: bool = True                             # degrees (else metres)
    legend_title: str = ""
    legend: tuple = ()                                  # ("scale", colours, low, high) or ("classes", [(label, colour)])
    boundary_rings: list = field(default_factory=list)  # [[(x, y), ...], ...] around the analysed area
    selected_rings: list = field(default_factory=list)  # the analysed area, drawn highlighted
    points: list = field(default_factory=list)          # [(x, y), ...]
    note: str = ""                                      # a line under the map (source, date, method)
    load_boundary: Callable[[str], list] | None = None  # a shapefile path -> its rings in the CRS (DEM page)
    # the whole boundary layer (e.g. the country), for the "country with magnified area" layout
    context_rings: list = field(default_factory=list)
    context_extent: tuple[float, float, float, float] | None = None


def ground_size(extent, geographic: bool) -> tuple[float, float]:
    """The extent's width and height on the ground, in metres."""
    west, south, east, north = extent
    if not geographic:
        return abs(east - west), abs(north - south)
    middle = math.radians((south + north) / 2)
    return abs(east - west) * 111_320.0 * max(0.01, math.cos(middle)), abs(north - south) * 110_540.0


def nice_distance(metres: float) -> float:
    if metres <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(metres))
    for step in (5, 2, 1):
        if step * power <= metres:
            return step * power
    return power


def distance_text(metres: float) -> str:
    """A distance as it reads well on a scale bar: 3 significant figures, km from 1 km."""
    if metres >= 1000:
        km = metres / 1000
        return f"{km:,.0f} km" if km >= 100 else f"{km:.3g} km"
    return f"{metres:.3g} m" if metres >= 1 else f"{metres * 100:.3g} cm"


def page_font(size: float, bold: bool = False) -> QFont:
    """A font sized in page units (the scene's points). Point sizes would be scaled twice when
    the page is painted into a 300-dpi PDF (once for the device, once for the page), so the
    hand-painted elements would print several times too big."""
    font = QFont(theme.SANS)
    font.setPixelSize(max(1, round(size)))
    font.setBold(bold)
    return font


# ================================================================ page items
class _Movable:
    def make_movable(self) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(10)


class _Resizable(_Movable):
    """A movable item with a handle (bottom-right) that resizes it while it is selected."""

    _resizing = False

    def handle_rect(self) -> QRectF:
        r = self.content_rect()
        return QRectF(r.right() - HANDLE / 2, r.bottom() - HANDLE / 2, HANDLE, HANDLE)

    def draw_handle(self, painter: QPainter) -> None:
        if self.isSelected():
            painter.save()
            painter.setPen(QPen(QColor("#0077B6"), 0.8, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.content_rect())
            painter.setPen(QPen(QColor("#FFFFFF"), 0.8))
            painter.setBrush(QColor("#0077B6"))
            painter.drawRect(self.handle_rect())
            painter.restore()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.isSelected() and self.handle_rect().adjusted(-3, -3, 3, 3).contains(event.pos()):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._resizing:
            self.resize_to(event.pos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        near = self.isSelected() and self.handle_rect().adjusted(-3, -3, 3, 3).contains(event.pos())
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if near else Qt.CursorShape.OpenHandCursor)
        super().hoverMoveEvent(event)


class MapFrameItem(QGraphicsItem):
    """A map: the raster in its true shape, centred in the frame, with vectors over it.

    ``extent`` is what the frame shows; the raster is placed by its own extent within it (so a
    locator frame shows the whole country with the small analysed surface in place)."""

    def __init__(self, spec: MapLayoutSpec, rect: QRectF, extent=None, rings=None, selected=None,
                 points=None, context: bool = False, caption: str = ""):
        super().__init__()
        self.spec = spec
        self.frame = rect
        self.extent = tuple(extent or spec.extent)
        self.rings = spec.boundary_rings if rings is None else rings
        self.selected = spec.selected_rings if selected is None else selected
        self.points = spec.points if points is None else points
        self.context = context            # a locator: boundaries in grey, the area boxed
        self.caption = caption
        self.show_boundaries = True
        self.show_points = True
        self.box: QRectF | None = None    # the magnified area, drawn as a box (locator)
        self._layout()

    def _layout(self) -> None:
        width_m, height_m = ground_size(self.extent, self.spec.geographic)
        aspect = width_m / height_m if height_m else 1.0
        inner = self.frame.adjusted(6, 6, -6, -6)
        if inner.width() / inner.height() > aspect:
            w, h = inner.height() * aspect, inner.height()
        else:
            w, h = inner.width(), inner.width() / aspect
        self.map_rect = QRectF(inner.center().x() - w / 2, inner.center().y() - h / 2, w, h)
        self.metres_per_point = width_m / w if w else 0.0
        self._boundary_path = self._path(self.rings)
        self._selected_path = self._path(self.selected)

    def to_page(self, x: float, y: float) -> QPointF:
        west, south, east, north = self.extent
        r = self.map_rect
        return QPointF(r.left() + (x - west) / ((east - west) or 1) * r.width(),
                       r.top() + (north - y) / ((north - south) or 1) * r.height())

    def rect_of(self, extent) -> QRectF:
        west, south, east, north = extent
        return QRectF(self.to_page(west, north), self.to_page(east, south)).normalized()

    def _path(self, rings) -> QPainterPath:
        path = QPainterPath()
        for ring in rings:
            if len(ring) < 2:
                continue
            path.addPolygon(QPolygonF([self.to_page(x, y) for x, y in ring]))
        return path

    def set_boundaries(self, rings) -> None:
        self.rings = rings
        self.spec.boundary_rings = rings
        self._boundary_path = self._path(rings)
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt API)
        return self.frame.adjusted(0, -12, 0, 0)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipRect(self.frame)
        painter.fillRect(self.frame, QColor("#FFFFFF"))
        if self.context and self.show_boundaries and not self._boundary_path.isEmpty():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#EEF1EF"))
            painter.drawPath(self._boundary_path)
        painter.drawImage(self.rect_of(self.spec.extent), self.spec.image)
        if self.show_boundaries and not self._boundary_path.isEmpty():
            painter.setPen(QPen(QColor("#8A9590" if self.context else "#1F2A44"), 0.4 if self.context else 0.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._boundary_path)
        if self.show_boundaries and not self._selected_path.isEmpty():
            painter.setPen(QPen(QColor("#0077B6"), 1.2 if self.context else 1.6))
            painter.drawPath(self._selected_path)
        if self.show_points and self.points and not self.context:
            painter.setPen(QPen(QColor("#FFFFFF"), 0.6))
            painter.setBrush(QColor("#111111"))
            for x, y in self.points:
                painter.drawEllipse(self.to_page(x, y), 1.8, 1.8)
        if self.box is not None:
            painter.setPen(QPen(QColor("#D7301F"), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.box)
        painter.setClipping(False)
        painter.setPen(QPen(INK, 0.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.frame)
        if self.caption:
            painter.setFont(page_font(7, bold=True))
            painter.drawText(QRectF(self.frame.left(), self.frame.top() - 11, self.frame.width(), 10),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, self.caption.upper())
        painter.restore()


class LeaderLines(QGraphicsItem):
    """Lines from the locator's box to the magnified map, so the eye follows from one to the other."""

    def __init__(self, box: QRectF, target: QRectF):
        super().__init__()
        self.box, self.target = box, target
        self.setZValue(5)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self.box.united(self.target)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#D7301F"), 0.6, Qt.PenStyle.DashLine))
        painter.drawLine(self.box.topRight(), self.target.topLeft())
        painter.drawLine(self.box.bottomRight(), self.target.bottomLeft())


# ---------------------------------------------------------------- north arrows
def _arrow_classic(p: QPainter, s: float) -> None:
    left = QPolygonF([QPointF(0, -s * 0.5), QPointF(-s * 0.25, s * 0.5), QPointF(0, s * 0.3)])
    right = QPolygonF([QPointF(0, -s * 0.5), QPointF(s * 0.25, s * 0.5), QPointF(0, s * 0.3)])
    p.setPen(QPen(INK, s * 0.025))
    p.setBrush(INK)
    p.drawPolygon(left)
    p.setBrush(QColor("#FFFFFF"))
    p.drawPolygon(right)


def _arrow_simple(p: QPainter, s: float) -> None:
    p.setPen(QPen(INK, s * 0.07, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(0, s * 0.5), QPointF(0, -s * 0.45))
    head = QPainterPath(QPointF(-s * 0.22, -s * 0.2))
    head.lineTo(0, -s * 0.5)
    head.lineTo(s * 0.22, -s * 0.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(head)


def _arrow_needle(p: QPainter, s: float) -> None:
    north = QPolygonF([QPointF(0, -s * 0.5), QPointF(-s * 0.09, 0), QPointF(s * 0.09, 0)])
    south = QPolygonF([QPointF(0, s * 0.5), QPointF(-s * 0.09, 0), QPointF(s * 0.09, 0)])
    p.setPen(QPen(INK, s * 0.02))
    p.setBrush(QColor("#C62828"))
    p.drawPolygon(north)
    p.setBrush(QColor("#FFFFFF"))
    p.drawPolygon(south)
    p.setBrush(INK)
    p.drawEllipse(QPointF(0, 0), s * 0.04, s * 0.04)


def _arrow_half(p: QPainter, s: float) -> None:
    body = QPolygonF([QPointF(0, -s * 0.5), QPointF(s * 0.28, s * 0.45), QPointF(0, s * 0.18),
                      QPointF(-s * 0.28, s * 0.45)])
    p.setPen(QPen(INK, s * 0.03))
    p.setBrush(QColor("#FFFFFF"))
    p.drawPolygon(body)
    p.setBrush(INK)
    p.drawPolygon(QPolygonF([QPointF(0, -s * 0.5), QPointF(0, s * 0.18), QPointF(-s * 0.28, s * 0.45)]))


def _arrow_triangle(p: QPainter, s: float) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    p.drawPolygon(QPolygonF([QPointF(0, -s * 0.5), QPointF(-s * 0.32, s * 0.1), QPointF(s * 0.32, s * 0.1)]))
    p.setFont(page_font(s * 0.36, bold=True))
    p.setPen(INK)
    p.drawText(QRectF(-s * 0.4, s * 0.1, s * 0.8, s * 0.42), Qt.AlignmentFlag.AlignCenter, "N")


def _arrow_circle(p: QPainter, s: float) -> None:
    p.setPen(QPen(INK, s * 0.04))
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(QPointF(0, s * 0.08), s * 0.36, s * 0.36)
    p.setBrush(INK)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([QPointF(0, -s * 0.5), QPointF(-s * 0.12, -s * 0.24), QPointF(s * 0.12, -s * 0.24)]))
    p.setFont(page_font(s * 0.36, bold=True))
    p.setPen(INK)
    p.drawText(QRectF(-s * 0.36, -s * 0.28, s * 0.72, s * 0.72), Qt.AlignmentFlag.AlignCenter, "N")


def _arrow_star(p: QPainter, s: float) -> None:
    p.setPen(QPen(INK, s * 0.02))
    for angle, filled in ((0, True), (90, False), (180, False), (270, False)):
        p.save()
        p.rotate(angle)
        p.setBrush(INK if filled else QColor("#FFFFFF"))
        p.drawPolygon(QPolygonF([QPointF(0, -s * 0.5), QPointF(-s * 0.1, -s * 0.1), QPointF(0, 0)]))
        p.setBrush(INK)
        p.drawPolygon(QPolygonF([QPointF(0, -s * 0.5), QPointF(s * 0.1, -s * 0.1), QPointF(0, 0)]))
        p.restore()


def _arrow_rose(p: QPainter, s: float) -> None:
    p.setPen(QPen(INK, s * 0.02))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(0, 0), s * 0.32, s * 0.32)
    for angle in (45, 135, 225, 315):           # the half winds, short
        p.save()
        p.rotate(angle)
        p.setBrush(QColor("#9AA5A1"))
        p.drawPolygon(QPolygonF([QPointF(0, -s * 0.3), QPointF(-s * 0.06, 0), QPointF(s * 0.06, 0)]))
        p.restore()
    _arrow_star(p, s * 0.9)
    p.setFont(page_font(s * 0.16, bold=True))
    p.setPen(INK)
    for text, x, y in (("E", s * 0.45, 0), ("S", 0, s * 0.45), ("W", -s * 0.45, 0)):
        p.drawText(QRectF(x - s * 0.1, y - s * 0.1, s * 0.2, s * 0.2), Qt.AlignmentFlag.AlignCenter, text)


NORTH_ARROWS: dict[str, tuple[str, Callable, bool]] = {   # key: (label, painter, draws its own "N")
    "classic": ("Classic", _arrow_classic, False),
    "rose": ("Compass rose", _arrow_rose, False),
    "star": ("Four-point star", _arrow_star, False),
    "half": ("Half-shaded arrow", _arrow_half, False),
    "simple": ("Simple arrow", _arrow_simple, False),
    "triangle": ("Triangle with N", _arrow_triangle, True),
    "circle": ("Circled N", _arrow_circle, True),
    "needle": ("Compass needle", _arrow_needle, False),
}


def north_arrow_icon(key: str, size: int = 40) -> QIcon:
    """A preview of a north-arrow style, for the list."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(size / 2, size / 2 + 2)
    NORTH_ARROWS[key][1](painter, size * 0.72)
    painter.end()
    return QIcon(pixmap)


class NorthArrowItem(QGraphicsItem, _Resizable):
    """A north arrow in one of the library's styles; resizable."""

    def __init__(self, style: str = "classic", size: float = 34.0):
        super().__init__()
        self.style = style
        self.size = size
        self.make_movable()
        self.setAcceptHoverEvents(True)

    def content_rect(self) -> QRectF:
        s = self.size
        return QRectF(-s * 0.55, -s * 0.5 - 15, s * 1.1, s * 1.05 + 15)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self.content_rect().adjusted(-HANDLE, -HANDLE, HANDLE, HANDLE)

    def set_style(self, style: str) -> None:
        self.prepareGeometryChange()
        self.style = style
        self.update()

    def set_size(self, size: float) -> None:
        self.prepareGeometryChange()
        self.size = max(14.0, min(160.0, size))
        self.update()

    on_resized: Callable[[float], None] | None = None   # e.g. keeps the dialog's size slider in step

    def resize_to(self, pos: QPointF) -> None:
        """Drag the bottom-right handle: the arrow grows or shrinks with it."""
        self.set_size(max(pos.x(), pos.y()) / 0.55)
        if self.on_resized is not None:
            self.on_resized(self.size)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        label, draw, own_n = NORTH_ARROWS.get(self.style, NORTH_ARROWS["classic"])
        painter.save()
        draw(painter, self.size)
        painter.restore()
        if not own_n:
            painter.setFont(page_font(max(8, self.size * 0.3), bold=True))
            painter.setPen(INK)
            painter.drawText(QRectF(-self.size * 0.4, -self.size * 0.5 - 15, self.size * 0.8, 14),
                             Qt.AlignmentFlag.AlignCenter, "N")
        self.draw_handle(painter)


class ScaleBarItem(QGraphicsItem, _Resizable):
    """A scale bar the user stretches or compresses by its right end; its distances follow live.

    It measures on the map frame it is placed over (the first frame whose map contains its
    start), so on a page with a locator and a magnified area it tells each map's scale."""

    MIN, MAX = 30.0, 400.0

    def __init__(self, frames, length: float = 120.0):
        super().__init__()
        self.frames = frames if isinstance(frames, list) else [frames]
        self.length = length
        self.make_movable()
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    @property
    def frame(self) -> MapFrameItem:
        """The map this bar measures on: the one under its start, else the first."""
        if self.scene() is not None:
            start = self.mapToScene(QPointF(0, 0))
            for frame in self.frames:
                if frame.map_rect.contains(start):
                    return frame
        return self.frames[0]

    def distance(self) -> tuple[float, float]:
        """(metres the bar spans now, its length in points)"""
        mpp = self.frame.metres_per_point
        return (mpp * self.length if mpp else 0.0), self.length

    def round_length(self) -> None:
        """Snap to the largest round distance (1, 2, 5 × 10ⁿ) not longer than now."""
        mpp = self.frame.metres_per_point
        if mpp:
            self.set_length(nice_distance(mpp * self.length) / mpp)

    def set_length(self, length: float) -> None:
        self.prepareGeometryChange()
        self.length = max(self.MIN, min(self.MAX, length))
        self.update()

    def content_rect(self) -> QRectF:
        return QRectF(0, -2, self.length, 9)

    def handle_rect(self) -> QRectF:   # the right end
        return QRectF(self.length - HANDLE / 2, -HANDLE / 2 + 2.5, HANDLE, HANDLE)

    def resize_to(self, pos: QPointF) -> None:
        self.set_length(pos.x())

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-34, -16, self.length + 68, 36)

    def itemChange(self, change, value):  # noqa: N802 - moved onto another map: its scale changes
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.update()
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        metres, length = self.distance()
        if length <= 0:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        segments = 4
        step = length / segments
        for i in range(segments):
            painter.setPen(QPen(INK, 0.6))
            painter.setBrush(INK if i % 2 == 0 else QColor("#FFFFFF"))
            painter.drawRect(QRectF(i * step, 0, step, 5))
        painter.setFont(page_font(7))
        painter.setPen(INK)
        painter.drawText(QRectF(-20, 6, 40, 10), Qt.AlignmentFlag.AlignCenter, "0")
        painter.drawText(QRectF(length / 2 - 34, 6, 68, 10), Qt.AlignmentFlag.AlignCenter, distance_text(metres / 2))
        painter.drawText(QRectF(length - 34, 6, 68, 10), Qt.AlignmentFlag.AlignCenter, distance_text(metres))
        self.draw_handle(painter)


class LegendItem(QGraphicsItem, _Movable):
    WIDTH = 150.0

    def __init__(self, title: str, legend: tuple):
        super().__init__()
        self.title = title
        self.legend = legend
        self.make_movable()

    def _height(self) -> float:
        if self.legend and self.legend[0] == "classes":
            return 26 + 14 * len(self.legend[1]) + 6
        return 26 + 12 + 16 + 6

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, self.WIDTH, self._height())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect()
        painter.setPen(QPen(QColor("#B8C2BE"), 0.6))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setFont(page_font(8, bold=True))
        painter.setPen(INK)
        painter.drawText(QRectF(8, 6, self.WIDTH - 16, 14), Qt.AlignmentFlag.AlignLeft, self.title)
        painter.setFont(page_font(8))
        if self.legend and self.legend[0] == "classes":
            for i, (label, colour) in enumerate(self.legend[1]):
                y = 26 + i * 14
                painter.setPen(QPen(QColor("#6B7A74"), 0.4))
                painter.setBrush(QColor(colour))
                painter.drawRect(QRectF(8, y, 16, 10))
                painter.setPen(INK)
                painter.drawText(QRectF(30, y - 2, self.WIDTH - 36, 14), Qt.AlignmentFlag.AlignVCenter, label)
        elif self.legend:
            _kind, colours, low, high = self.legend
            bar = QRectF(8, 26, self.WIDTH - 16, 10)
            gradient = QLinearGradient(bar.left(), 0, bar.right(), 0)
            last = max(1, len(colours) - 1)
            for i, colour in enumerate(colours):
                gradient.setColorAt(i / last, QColor(colour))
            painter.setPen(QPen(QColor("#6B7A74"), 0.4))
            painter.setBrush(QBrush(gradient))
            painter.drawRect(bar)
            painter.setPen(INK)
            painter.drawText(QRectF(8, 38, 60, 14), Qt.AlignmentFlag.AlignLeft, _fmt(low))
            painter.drawText(QRectF(self.WIDTH - 68, 38, 60, 14), Qt.AlignmentFlag.AlignRight, _fmt(high))


def _fmt(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1000 or value == int(value):
        return f"{value:,.0f}"
    return f"{value:.2f}" if magnitude >= 1 else f"{value:.3g}"


class _Title(QGraphicsTextItem, _Movable):
    def __init__(self, text: str):
        super().__init__(text)
        font = QFont(theme.SERIF)
        font.setPointSizeF(16)
        font.setBold(True)
        self.setFont(font)
        self.setDefaultTextColor(INK)
        self.make_movable()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt API) - double-click to edit in place
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus()
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        super().focusOutEvent(event)


# ================================================================ the dialog
class MapLayoutDialog(QDialog):
    def __init__(self, spec: MapLayoutSpec, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export map as PDF")
        self.resize(1240, 840)
        self.spec = spec
        self.exported: str = ""
        self.overview_item: MapFrameItem | None = None

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(QColor("#9AA5A1"))
        self.view.setFrameShape(QFrame.Shape.NoFrame)

        self.title_edit = QLineEdit(spec.title)
        self.page_box = QComboBox()
        self.page_box.addItems(list(PAGE_SIZES))
        self.orientation_box = QComboBox()
        self.orientation_box.addItems(["Landscape", "Portrait"])
        self.layout_box = QComboBox()
        self.layout_box.addItem("Area only", AREA_ONLY)
        self.layout_box.addItem("Country with magnified area", WITH_LOCATOR)
        has_context = bool(spec.context_rings) and spec.context_extent is not None
        self.layout_box.setEnabled(has_context)
        self.layout_box.setToolTip("The whole boundary layer (e.g. the country) with the analysed area boxed, and "
                                   "the area magnified beside it" if has_context else
                                   "Needs a boundary layer (open boundaries on the IDW page)")
        self.toggles: dict[str, QCheckBox] = {}
        for key, label in (("title", "Title"), ("north", "North arrow"), ("scale", "Scale bar"),
                           ("legend", "Legend"), ("boundaries", "Boundary layer"), ("points", "Sample points"),
                           ("note", "Note under the map")):
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self._apply_toggles)
            self.toggles[key] = box
        self.toggles["points"].setVisible(bool(spec.points))

        self.arrow_box = QComboBox()
        for key, (label, _draw, _n) in NORTH_ARROWS.items():
            self.arrow_box.addItem(north_arrow_icon(key), label, key)
        from PyQt6.QtCore import QSize

        self.arrow_box.setIconSize(QSize(28, 28))
        self.arrow_size = QSlider(Qt.Orientation.Horizontal)
        self.arrow_size.setRange(14, 160)
        self.arrow_size.setValue(34)
        self.round_button = QPushButton("Round the scale bar", objectName="SecondaryButton")
        self.round_button.setToolTip("Snap the bar to a round distance (1, 2 or 5 × 10ⁿ)")

        self.boundary_button = QPushButton("Add boundary layer…", objectName="SecondaryButton")
        self.boundary_button.setVisible(spec.load_boundary is not None)
        self.reset_button = QPushButton("Reset positions", objectName="SecondaryButton")
        self.export_button = QPushButton("Export PDF…", objectName="PrimaryButton")
        self.close_button = QPushButton("Close", objectName="SecondaryButton")
        self.message = QLabel(objectName="Muted")
        self.message.setWordWrap(True)

        panel = QVBoxLayout()
        panel.setSpacing(7)
        panel.addWidget(QLabel("Title", objectName="Muted"))
        panel.addWidget(self.title_edit)
        row = QHBoxLayout()
        row.addWidget(self.page_box)
        row.addWidget(self.orientation_box)
        panel.addWidget(QLabel("Page", objectName="Muted"))
        panel.addLayout(row)
        panel.addWidget(QLabel("Layout", objectName="Muted"))
        panel.addWidget(self.layout_box)
        panel.addSpacing(4)
        panel.addWidget(QLabel("North arrow", objectName="Muted"))
        panel.addWidget(self.arrow_box)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Size", objectName="Muted"))
        size_row.addWidget(self.arrow_size, 1)
        panel.addLayout(size_row)
        panel.addWidget(self.round_button)
        panel.addSpacing(4)
        panel.addWidget(QLabel("Show on the page", objectName="Muted"))
        for box in self.toggles.values():
            panel.addWidget(box)
        panel.addWidget(self.boundary_button)
        hint = QLabel("Drag the elements to place them. Select the north arrow or the scale bar and drag its handle "
                      "to resize it: the scale bar's distances follow as you stretch it. Double-click the title to "
                      "edit it on the page.", objectName="Muted")
        hint.setWordWrap(True)
        panel.addWidget(hint)
        panel.addStretch(1)
        panel.addWidget(self.message)
        panel.addWidget(self.reset_button)
        panel.addWidget(self.export_button)
        panel.addWidget(self.close_button)
        side = QWidget()
        side.setLayout(panel)
        side.setFixedWidth(270)

        layout = QHBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addWidget(side)
        theming.styled(self, lambda: f"QDialog {{ background: {theme.WHITE}; }}")

        self.title_edit.textChanged.connect(lambda text: self.title_item.setPlainText(text))
        self.page_box.currentIndexChanged.connect(lambda *_: self.build())
        self.orientation_box.currentIndexChanged.connect(lambda *_: self.build())
        self.layout_box.currentIndexChanged.connect(lambda *_: self.build())
        self.arrow_box.currentIndexChanged.connect(lambda *_: self.north_item.set_style(self.arrow_box.currentData()))
        self.arrow_size.valueChanged.connect(lambda value: self.north_item.set_size(value))
        self.round_button.clicked.connect(lambda: self.scale_item.round_length())
        self.reset_button.clicked.connect(self.build)
        self.export_button.clicked.connect(self.choose_and_export)
        self.close_button.clicked.connect(self.accept)
        self.boundary_button.clicked.connect(self._add_boundary)
        self.build()

    # ------------------------------------------------------------- the page
    def page_layout(self) -> QPageLayout:
        orientation = QPageLayout.Orientation.Landscape if self.orientation_box.currentText() == "Landscape" \
            else QPageLayout.Orientation.Portrait
        return QPageLayout(QPageSize(PAGE_SIZES[self.page_box.currentText()]), orientation, QMarginsF(0, 0, 0, 0))

    def page_rect(self) -> QRectF:
        return QRectF(self.page_layout().fullRect(QPageLayout.Unit.Point))

    def build(self) -> None:
        """Lay the page out afresh (elements in their default places)."""
        self.scene.clear()
        self.overview_item = None
        page = self.page_rect()
        self.scene.setSceneRect(page.adjusted(-20, -20, 20, 20))
        self.page_item = self.scene.addRect(page, QPen(QColor("#7A8580"), 0.5), QBrush(QColor("#FFFFFF")))
        self.page_item.setZValue(-10)
        top = MARGIN + 34
        bottom = page.height() - MARGIN - 18
        area = QRectF(MARGIN, top, page.width() - 2 * MARGIN, bottom - top)
        frames: list[MapFrameItem] = []
        if self.layout_box.currentData() == WITH_LOCATOR and self.layout_box.isEnabled():
            gap = 18.0
            landscape = area.width() >= area.height()
            if landscape:
                split = area.width() * 0.56
                locator_rect = QRectF(area.left(), area.top() + 12, split - gap / 2, area.height() - 12)
                detail_rect = QRectF(area.left() + split + gap / 2, area.top() + 12, area.width() - split - gap / 2,
                                     area.height() - 12)
            else:
                split = area.height() * 0.5
                locator_rect = QRectF(area.left(), area.top() + 12, area.width(), split - gap / 2 - 12)
                detail_rect = QRectF(area.left(), area.top() + split + gap / 2 + 12, area.width(),
                                     area.height() - split - gap / 2 - 12)
            self.overview_item = MapFrameItem(self.spec, locator_rect, extent=self.spec.context_extent,
                                              rings=self.spec.context_rings, selected=self.spec.selected_rings,
                                              points=[], context=True, caption="Location")
            self.frame_item = MapFrameItem(self.spec, detail_rect, caption="Magnified")
            self.overview_item.box = self.overview_item.rect_of(self.frame_item.extent).adjusted(-1.5, -1.5, 1.5, 1.5)
            self.scene.addItem(self.overview_item)
            self.scene.addItem(self.frame_item)
            self.scene.addItem(LeaderLines(self.overview_item.box, self.frame_item.map_rect))
            frames = [self.frame_item, self.overview_item]
        else:
            self.frame_item = MapFrameItem(self.spec, area)
            self.scene.addItem(self.frame_item)
            frames = [self.frame_item]
        frame = self.frame_item.frame

        self.title_item = _Title(self.title_edit.text())
        self.scene.addItem(self.title_item)
        self.title_item.setPos(page.width() / 2 - self.title_item.boundingRect().width() / 2, MARGIN - 4)

        self.north_item = NorthArrowItem(self.arrow_box.currentData() or "classic", self.arrow_size.value())
        self.scene.addItem(self.north_item)
        self.north_item.setPos(frame.right() - 34, frame.top() + 40)
        self.north_item.on_resized = self._arrow_resized

        self.scale_item = ScaleBarItem(frames)
        self.scene.addItem(self.scale_item)
        self.scale_item.setPos(frame.right() - self.scale_item.length - 34, frame.bottom() - 28)
        self.scale_item.round_length()

        self.legend_item = LegendItem(self.spec.legend_title, self.spec.legend)
        self.scene.addItem(self.legend_item)
        self.legend_item.setPos(frame.left() + 12, frame.bottom() - self.legend_item.boundingRect().height() - 12)

        self.note_item = self.scene.addText(self.spec.note)
        font = QFont(theme.SANS)
        font.setPointSizeF(7)
        self.note_item.setFont(font)
        self.note_item.setDefaultTextColor(QColor("#55625D"))
        self.note_item.setPos(MARGIN, page.height() - MARGIN - 16)
        self._apply_toggles()
        self.view.fitInView(page.adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)

    def _arrow_resized(self, size: float) -> None:
        self.arrow_size.blockSignals(True)
        self.arrow_size.setValue(round(size))
        self.arrow_size.blockSignals(False)

    def _apply_toggles(self, *_args) -> None:
        if not hasattr(self, "frame_item"):
            return
        shown = {key: box.isChecked() for key, box in self.toggles.items()}
        self.title_item.setVisible(shown["title"])
        self.north_item.setVisible(shown["north"])
        self.scale_item.setVisible(shown["scale"])
        self.legend_item.setVisible(shown["legend"] and bool(self.spec.legend))
        self.note_item.setVisible(shown["note"] and bool(self.spec.note))
        for frame in (self.frame_item, self.overview_item):
            if frame is not None:
                frame.show_boundaries = shown["boundaries"]
                frame.show_points = shown["points"]
                frame.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API) - fit the page once the view has its size
        super().showEvent(event)
        self.view.fitInView(self.page_rect().adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if hasattr(self, "page_item"):
            self.view.fitInView(self.page_rect().adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)

    def _add_boundary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Boundary layer", "", "Shapefiles (*.shp)")
        if not path:
            return
        try:
            rings = self.spec.load_boundary(path)
        except Exception as exc:  # noqa: BLE001 - shown, never fatal
            self.message.setText(str(exc))
            return
        self.frame_item.set_boundaries(rings)
        self.toggles["boundaries"].setChecked(True)
        self.message.setText(f"Boundary layer: {Path(path).name}")

    # ------------------------------------------------------------- export
    def choose_and_export(self) -> None:
        suggested = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.title_edit.text()).strip() or "map"
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", f"{suggested}.pdf", "PDF (*.pdf)")
        if path:
            self.export(path)

    def export(self, path: str) -> str:
        """Paint the page into a PDF at ``path``; returns the path."""
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.scene.clearSelection()                       # no selection outlines or handles on paper
        writer = QPdfWriter(path)
        writer.setPageLayout(self.page_layout())
        writer.setResolution(300)
        writer.setTitle(self.title_edit.text())
        writer.setCreator("GEE-Assist")
        painter = QPainter(writer)
        try:
            target = QRectF(0, 0, writer.width(), writer.height())
            self.page_item.setPen(QPen(Qt.PenStyle.NoPen))     # no page outline on paper
            self.scene.render(painter, target, self.page_rect(), Qt.AspectRatioMode.KeepAspectRatio)
        finally:
            painter.end()
            self.page_item.setPen(QPen(QColor("#7A8580"), 0.5))
        self.exported = path
        self.message.setText(f"Saved {Path(path).name}")
        return path


def page_size_points(name: str, landscape: bool) -> QSizeF:
    size = QPageSize(PAGE_SIZES[name]).size(QPageSize.Unit.Point)
    return QSizeF(size.height(), size.width()) if landscape else size
