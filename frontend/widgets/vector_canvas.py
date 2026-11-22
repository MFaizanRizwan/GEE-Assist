"""Draws a vector map (a loaded shapefile) with mouse-wheel zoom, drag-to-pan and
double-click-to-fit, like a desktop GIS canvas.

Everything is in WGS84 longitude/latitude; the canvas keeps a simple fit transform from
geographic coordinates to screen pixels (latitude grows upward, so the y axis is flipped).
It reports the feature under the pointer (``feature_hovered``) and the one clicked
(``feature_clicked``) by their index in the layer, so the page can identify features and
keep the attribute table in step.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from backend.dto.vector_dto import MULTIPOINT, POINT, POLYGON, POLYLINE, VectorLayerDTO
from frontend import theme

ZOOM_STEP = 1.25
MAX_ZOOM = 5000.0
MIN_ZOOM = 1.0
MARGIN = 24          # screen pixels kept around the layer when fitted
HIT_TOLERANCE = 6    # screen pixels: how close the pointer must be to pick a line or point


class VectorCanvas(QWidget):
    feature_hovered = pyqtSignal(int)   # index of the feature under the pointer, or -1
    feature_clicked = pyqtSignal(int)   # index of the feature clicked, or -1

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 200)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._layer: VectorLayerDTO | None = None
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)   # extra pixel offset on top of the fit transform
        self._selected = -1
        self._hover = -1
        self._dragging = False
        self._drag_from = QPointF()
        self._pan_from = QPointF()
        self._moved = False
        # Symbology (ArcGIS-like defaults): translucent fill, solid outline, round point markers.
        self._fill = QColor(theme.OCEAN)
        self._fill.setAlpha(90)
        self._outline = QColor(theme.OCEAN)
        self._point_size = 7

    # ------------------------------------------------------------- data & style
    def set_layer(self, layer: VectorLayerDTO | None) -> None:
        self._layer = layer
        self._selected = -1
        self._hover = -1
        self.fit()

    def set_colours(self, fill: QColor, outline: QColor) -> None:
        self._fill, self._outline = QColor(fill), QColor(outline)
        self.update()

    def set_point_size(self, size: int) -> None:
        self._point_size = max(2, int(size))
        self.update()

    def set_selected(self, index: int) -> None:
        if index != self._selected:
            self._selected = index
            self.update()

    def selected(self) -> int:
        return self._selected

    # ------------------------------------------------------------- view
    def fit(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def zoom_to_feature(self, index: int) -> None:
        """Centre and zoom in on one feature (ArcGIS "Zoom to selected")."""
        if self._layer is None or not (0 <= index < len(self._layer.features)):
            return
        minx, miny, maxx, maxy = self._layer.features[index].bounds
        lminx, lminy, lmaxx, lmaxy = self._padded_bounds()
        fw, fh = max(maxx - minx, 1e-9), max(maxy - miny, 1e-9)
        base_w, base_h = (lmaxx - lminx), (lmaxy - lminy)
        # Zoom so the feature fills ~60% of the view, capped.
        self._zoom = min(MAX_ZOOM, max(1.0, 0.6 * min(base_w / fw, base_h / fh)))
        base = self._base_scale()
        scale = base * self._zoom
        gcx, gcy = (lminx + lmaxx) / 2, (lminy + lmaxy) / 2
        fcx, fcy = (minx + maxx) / 2, (miny + maxy) / 2
        # Pan so the feature's centre sits at the widget's centre.
        self._pan = QPointF((gcx - fcx) * scale, -(gcy - fcy) * scale)
        self._selected = index
        self.update()

    # ------------------------------------------------------------- transform
    def _padded_bounds(self) -> tuple[float, float, float, float]:
        minx, miny, maxx, maxy = self._layer.bounds
        w, h = maxx - minx, maxy - miny
        if w <= 0:
            minx, maxx = minx - 0.5, maxx + 0.5
        if h <= 0:
            miny, maxy = miny - 0.5, maxy + 0.5
        return minx, miny, maxx, maxy

    def _base_scale(self) -> float:
        minx, miny, maxx, maxy = self._padded_bounds()
        gw, gh = max(maxx - minx, 1e-9), max(maxy - miny, 1e-9)
        return min((self.width() - 2 * MARGIN) / gw, (self.height() - 2 * MARGIN) / gh)

    def _to_screen(self, lon: float, lat: float) -> QPointF:
        minx, miny, maxx, maxy = self._padded_bounds()
        gcx, gcy = (minx + maxx) / 2, (miny + maxy) / 2
        scale = self._base_scale() * self._zoom
        cx, cy = self.width() / 2, self.height() / 2
        return QPointF(cx + (lon - gcx) * scale + self._pan.x(),
                       cy - (lat - gcy) * scale + self._pan.y())

    def _to_geo(self, x: float, y: float) -> tuple[float, float]:
        minx, miny, maxx, maxy = self._padded_bounds()
        gcx, gcy = (minx + maxx) / 2, (miny + maxy) / 2
        scale = self._base_scale() * self._zoom
        cx, cy = self.width() / 2, self.height() / 2
        return (gcx + (x - self._pan.x() - cx) / scale,
                gcy - (y - self._pan.y() - cy) / scale)

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.FIELD_BG))
        if self._layer is None or not self._layer.features:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open a shapefile to see it here.")
            return
        for index, feature in enumerate(self._layer.features):
            self._draw_feature(painter, feature, index)

    def _draw_feature(self, painter: QPainter, feature, index: int) -> None:
        selected = index == self._selected
        hovered = index == self._hover
        outline = QColor(theme.LEAF) if selected else QColor(self._outline)
        width = 3.0 if selected else (2.0 if hovered else 1.3)
        pen = QPen(outline, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        if feature.kind == POLYGON:
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)  # inner rings become holes
            for ring in feature.parts:
                polygon = QPolygonF([self._to_screen(lon, lat) for lon, lat in ring])
                path.addPolygon(polygon)
                path.closeSubpath()
            fill = QColor(self._fill)
            if selected:
                fill = QColor(theme.MINT)
                fill.setAlpha(150)
            painter.setBrush(QBrush(fill))
            painter.setPen(pen)
            painter.drawPath(path)
        elif feature.kind == POLYLINE:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            for ring in feature.parts:
                painter.drawPolyline(QPolygonF([self._to_screen(lon, lat) for lon, lat in ring]))
        else:  # POINT / MULTIPOINT
            radius = (self._point_size + 3) / 2 if selected else self._point_size / 2
            painter.setPen(QPen(outline, 1.2))
            painter.setBrush(QBrush(QColor(theme.LEAF) if selected else QColor(self._fill.red(), self._fill.green(),
                                                                               self._fill.blue())))
            for ring in feature.parts:
                for lon, lat in ring:
                    painter.drawEllipse(self._to_screen(lon, lat), radius, radius)

    # ------------------------------------------------------------- mouse
    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._layer is None:
            return
        pos = event.position()
        before = self._to_geo(pos.x(), pos.y())
        factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP
        self._zoom = min(MAX_ZOOM, max(MIN_ZOOM, self._zoom * factor))
        after_screen = self._to_screen(*before)
        self._pan += QPointF(pos.x() - after_screen.x(), pos.y() - after_screen.y())  # keep point under cursor
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._moved = False
            self._drag_from = event.position()
            self._pan_from = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._dragging:
            delta = event.position() - self._drag_from
            if abs(delta.x()) + abs(delta.y()) > 3:
                self._moved = True
            self._pan = self._pan_from + delta
            self.update()
            return
        index = self._feature_at(event.position())
        if index != self._hover:
            self._hover = index
            self.feature_hovered.emit(index)
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if not self._moved:  # a click, not a pan: identify the feature there
            index = self._feature_at(event.position())
            self._selected = index
            self.feature_clicked.emit(index)
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.fit()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._hover != -1:
            self._hover = -1
            self.feature_hovered.emit(-1)
            self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.update()

    # ------------------------------------------------------------- hit testing
    def _feature_at(self, pos: QPointF) -> int:
        if self._layer is None:
            return -1
        for index in range(len(self._layer.features) - 1, -1, -1):  # topmost (drawn last) first
            feature = self._layer.features[index]
            if feature.kind == POLYGON and self._in_polygon(feature, pos):
                return index
            if feature.kind == POLYLINE and self._near_line(feature, pos):
                return index
            if feature.kind in (POINT, MULTIPOINT) and self._near_point(feature, pos):
                return index
        return -1

    def _in_polygon(self, feature, pos: QPointF) -> bool:
        rings = [[self._to_screen(lon, lat) for lon, lat in ring] for ring in feature.parts]
        if not rings or not _point_in_ring(rings[0], pos):
            return False
        return not any(_point_in_ring(hole, pos) for hole in rings[1:])  # inside a hole = outside

    def _near_line(self, feature, pos: QPointF) -> bool:
        for ring in feature.parts:
            pts = [self._to_screen(lon, lat) for lon, lat in ring]
            for a, b in zip(pts, pts[1:]):
                if _distance_to_segment(pos, a, b) <= HIT_TOLERANCE:
                    return True
        return False

    def _near_point(self, feature, pos: QPointF) -> bool:
        reach = self._point_size / 2 + HIT_TOLERANCE
        for ring in feature.parts:
            for lon, lat in ring:
                screen = self._to_screen(lon, lat)
                if (screen.x() - pos.x()) ** 2 + (screen.y() - pos.y()) ** 2 <= reach ** 2:
                    return True
        return False


def _point_in_ring(points: list[QPointF], pos: QPointF) -> bool:
    """Ray-casting point-in-polygon test, in screen coordinates."""
    inside = False
    n = len(points)
    if n < 3:
        return False
    x, y = pos.x(), pos.y()
    j = n - 1
    for i in range(n):
        xi, yi = points[i].x(), points[i].y()
        xj, yj = points[j].x(), points[j].y()
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _distance_to_segment(p: QPointF, a: QPointF, b: QPointF) -> float:
    ax, ay, bx, by, px, py = a.x(), a.y(), b.x(), b.y(), p.x(), p.y()
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
