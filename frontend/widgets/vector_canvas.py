"""Draws a vector map (a loaded shapefile) with mouse-wheel zoom, drag-to-pan and
double-click-to-fit, like a desktop GIS canvas.

Everything is in WGS84 longitude/latitude; the canvas keeps a simple fit transform from
geographic coordinates to screen pixels (latitude grows upward, so the y axis is flipped).
It reports the feature under the pointer (``feature_hovered``) and the one clicked
(``feature_clicked``) by their index in the layer.

Admin-boundary layers have huge vertex counts, so the screen geometry is built once (with
numpy) and cached: panning only shifts the cached geometry, a repaint (e.g. on hover) just
redraws it, and vertices that fall on the same pixel are dropped. Only zooming or resizing
rebuilds the cache. Off-screen features are skipped entirely.
"""

from __future__ import annotations

import numpy as np
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


class _Cached:
    """Screen-space geometry of one feature, for the current zoom (shifted by pan at draw time)."""

    __slots__ = ("kind", "path", "polys", "rings", "bbox")

    def __init__(self, kind: str):
        self.kind = kind
        self.path: QPainterPath | None = None          # filled path for polygons (holes via even-odd)
        self.polys: list[QPolygonF] = []               # polylines
        self.rings: list[np.ndarray] = []              # decimated screen coords (M, 2) for hit-testing
        self.bbox = (0.0, 0.0, 0.0, 0.0)               # screen bounds at cache pan


class VectorCanvas(QWidget):
    feature_hovered = pyqtSignal(int)   # index of the feature under the pointer, or -1
    feature_clicked = pyqtSignal(int)   # index of the feature clicked, or -1

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 200)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._layer: VectorLayerDTO | None = None
        self._geo: list[list[np.ndarray]] = []          # per feature: list of rings as (N, 2) lon/lat arrays
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._selected = -1
        self._hover = -1
        self._dragging = False
        self._drag_from = QPointF()
        self._pan_from = QPointF()
        self._moved = False
        # Cache of screen geometry, valid for a (width, height, zoom) and built at ``_cache_pan``.
        self._cache: list[_Cached] = []
        self._cache_key: tuple | None = None
        self._cache_pan = QPointF(0.0, 0.0)
        self._fill = QColor(theme.OCEAN)
        self._fill.setAlpha(90)
        self._outline = QColor(theme.OCEAN)
        self._point_size = 7

    # ------------------------------------------------------------- data & style
    def set_layer(self, layer: VectorLayerDTO | None) -> None:
        self._layer = layer
        self._selected = -1
        self._hover = -1
        self._geo = []
        if layer is not None:
            for feature in layer.features:
                self._geo.append([np.asarray(ring, dtype="float64").reshape(-1, 2) for ring in feature.parts if ring])
        self._invalidate()
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
        self._invalidate()
        self.update()

    def zoom_to_feature(self, index: int) -> None:
        if self._layer is None or not (0 <= index < len(self._layer.features)):
            return
        minx, miny, maxx, maxy = self._layer.features[index].bounds
        lminx, lminy, lmaxx, lmaxy = self._padded_bounds()
        fw, fh = max(maxx - minx, 1e-9), max(maxy - miny, 1e-9)
        base_w, base_h = (lmaxx - lminx), (lmaxy - lminy)
        self._zoom = min(MAX_ZOOM, max(1.0, 0.6 * min(base_w / fw, base_h / fh)))
        scale = self._base_scale() * self._zoom
        gcx, gcy = (lminx + lmaxx) / 2, (lminy + lmaxy) / 2
        fcx, fcy = (minx + maxx) / 2, (miny + maxy) / 2
        self._pan = QPointF((gcx - fcx) * scale, -(gcy - fcy) * scale)
        self._selected = index
        self._invalidate()
        self.update()

    # ------------------------------------------------------------- transform
    def _padded_bounds(self) -> tuple[float, float, float, float]:
        minx, miny, maxx, maxy = self._layer.bounds
        if maxx - minx <= 0:
            minx, maxx = minx - 0.5, maxx + 0.5
        if maxy - miny <= 0:
            miny, maxy = miny - 0.5, maxy + 0.5
        return minx, miny, maxx, maxy

    def _base_scale(self) -> float:
        minx, miny, maxx, maxy = self._padded_bounds()
        gw, gh = max(maxx - minx, 1e-9), max(maxy - miny, 1e-9)
        return min((self.width() - 2 * MARGIN) / gw, (self.height() - 2 * MARGIN) / gh)

    def _transform(self, pan: QPointF) -> tuple[float, float, float]:
        """(scale, offset_x, offset_y): screen_x = lon*scale + ox, screen_y = -lat*scale + oy."""
        minx, miny, maxx, maxy = self._padded_bounds()
        gcx, gcy = (minx + maxx) / 2, (miny + maxy) / 2
        scale = self._base_scale() * self._zoom
        cx, cy = self.width() / 2, self.height() / 2
        return scale, cx - gcx * scale + pan.x(), cy + gcy * scale + pan.y()

    def _to_screen(self, lon: float, lat: float) -> QPointF:
        scale, ox, oy = self._transform(self._pan)
        return QPointF(lon * scale + ox, -lat * scale + oy)

    def _to_geo(self, x: float, y: float) -> tuple[float, float]:
        scale, ox, oy = self._transform(self._pan)
        return (x - ox) / scale, (oy - y) / scale

    # ------------------------------------------------------------- cache
    def _invalidate(self) -> None:
        self._cache_key = None

    def _ensure_cache(self) -> None:
        key = (self.width(), self.height(), round(self._zoom, 6))
        if self._cache_key == key:
            return
        self._cache_pan = QPointF(self._pan)
        scale, ox, oy = self._transform(self._cache_pan)
        self._cache = [self._cache_feature(rings, self._layer.features[i].kind, scale, ox, oy)
                       for i, rings in enumerate(self._geo)] if self._layer is not None else []
        self._cache_key = key

    def _cache_feature(self, rings: list[np.ndarray], kind: str, scale: float, ox: float, oy: float) -> _Cached:
        cached = _Cached(kind)
        bounds = [np.inf, np.inf, -np.inf, -np.inf]
        path = QPainterPath() if kind == POLYGON else None
        if path is not None:
            path.setFillRule(Qt.FillRule.OddEvenFill)
        for ring in rings:
            if ring.shape[0] == 0:
                continue
            sx = ring[:, 0] * scale + ox
            sy = -ring[:, 1] * scale + oy
            sx, sy = _decimate(sx, sy)
            if sx.size == 0:
                continue
            bounds[0] = min(bounds[0], float(sx.min()))
            bounds[1] = min(bounds[1], float(sy.min()))
            bounds[2] = max(bounds[2], float(sx.max()))
            bounds[3] = max(bounds[3], float(sy.max()))
            polygon = _polygon(sx, sy)
            cached.rings.append(np.column_stack([sx, sy]))
            if kind == POLYGON:
                path.addPolygon(polygon)
                path.closeSubpath()
            else:
                cached.polys.append(polygon)
        cached.path = path
        cached.bbox = tuple(bounds) if np.isfinite(bounds[0]) else (0.0, 0.0, 0.0, 0.0)
        return cached

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.FIELD_BG))
        if self._layer is None or not self._geo:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open a shapefile to see it here.")
            return
        self._ensure_cache()
        delta = self._pan - self._cache_pan
        painter.translate(delta)
        # Cull against the view in cache space (shift the widget rect by -delta).
        view = QRectF(-delta.x(), -delta.y(), self.width(), self.height()).adjusted(-20, -20, 20, 20)
        for index, cached in enumerate(self._cache):
            if not _overlaps(cached.bbox, view):
                continue
            self._draw(painter, cached, index)

    def _draw(self, painter: QPainter, cached: _Cached, index: int) -> None:
        selected = index == self._selected
        outline = QColor(theme.LEAF) if selected else QColor(self._outline)
        width = 2.5 if selected else 1.2
        pen = QPen(outline, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        if cached.kind == POLYGON and cached.path is not None:
            fill = QColor(self._fill)
            if selected:
                fill = QColor(theme.MINT)
                fill.setAlpha(160)
            painter.setBrush(QBrush(fill))
            painter.setPen(pen)
            painter.drawPath(cached.path)
        elif cached.kind == POLYLINE:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            for polygon in cached.polys:
                painter.drawPolyline(polygon)
        else:  # POINT / MULTIPOINT
            radius = (self._point_size + 3) / 2 if selected else self._point_size / 2
            painter.setPen(QPen(outline, 1.2))
            painter.setBrush(QBrush(QColor(theme.LEAF) if selected
                                    else QColor(self._fill.red(), self._fill.green(), self._fill.blue())))
            for ring in cached.rings:
                for x, y in ring:
                    painter.drawEllipse(QPointF(float(x), float(y)), radius, radius)

    # ------------------------------------------------------------- mouse
    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._layer is None:
            return
        pos = event.position()
        before = self._to_geo(pos.x(), pos.y())
        factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP
        self._zoom = min(MAX_ZOOM, max(MIN_ZOOM, self._zoom * factor))
        after = self._to_screen(*before)
        self._pan += QPointF(pos.x() - after.x(), pos.y() - after.y())  # keep the point under the cursor
        self._invalidate()
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
            self._pan = self._pan_from + delta  # panning only shifts the cached geometry; no rebuild
            self.update()
            return
        index = self._feature_at(event.position())
        if index != self._hover:
            self._hover = index
            self.feature_hovered.emit(index)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if not self._moved:
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

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._invalidate()
        self.update()

    # ------------------------------------------------------------- hit testing
    def _feature_at(self, pos: QPointF) -> int:
        if self._layer is None:
            return -1
        self._ensure_cache()
        if not self._cache:
            return -1
        delta = self._pan - self._cache_pan
        point = QPointF(pos.x() - delta.x(), pos.y() - delta.y())  # into cache space
        x, y = point.x(), point.y()
        for index in range(len(self._cache) - 1, -1, -1):  # topmost first
            cached = self._cache[index]
            minx, miny, maxx, maxy = cached.bbox
            margin = HIT_TOLERANCE + (self._point_size if cached.kind in (POINT, MULTIPOINT) else 0)
            if not (minx - margin <= x <= maxx + margin and miny - margin <= y <= maxy + margin):
                continue
            if cached.kind == POLYGON and _in_polygon(cached.rings, x, y):
                return index
            if cached.kind == POLYLINE and _near_line(cached.rings, x, y):
                return index
            if cached.kind in (POINT, MULTIPOINT) and _near_point(cached.rings, x, y, self._point_size / 2 + HIT_TOLERANCE):
                return index
        return -1


# ------------------------------------------------------------- numpy / geometry helpers
def _decimate(sx: np.ndarray, sy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop consecutive points that round to the same pixel (keeps the shape, far fewer points)."""
    if sx.size <= 2:
        return sx, sy
    xr, yr = np.round(sx), np.round(sy)
    keep = np.empty(sx.size, dtype=bool)
    keep[0] = True
    keep[1:] = (xr[1:] != xr[:-1]) | (yr[1:] != yr[:-1])
    keep[-1] = True
    return sx[keep], sy[keep]


def _polygon(sx: np.ndarray, sy: np.ndarray) -> QPolygonF:
    polygon = QPolygonF()
    append = polygon.append
    for i in range(sx.size):
        append(QPointF(float(sx[i]), float(sy[i])))
    return polygon


def _overlaps(bbox: tuple[float, float, float, float], rect: QRectF) -> bool:
    minx, miny, maxx, maxy = bbox
    return not (maxx < rect.left() or minx > rect.right() or maxy < rect.top() or miny > rect.bottom())


def _in_polygon(rings: list[np.ndarray], x: float, y: float) -> bool:
    if not rings or not _ray_cast(rings[0], x, y):
        return False
    return not any(_ray_cast(hole, x, y) for hole in rings[1:])


def _ray_cast(ring: np.ndarray, x: float, y: float) -> bool:
    """Vectorised point-in-polygon (ray casting) on a screen-space ring."""
    n = ring.shape[0]
    if n < 3:
        return False
    xi, yi = ring[:, 0], ring[:, 1]
    xj, yj = np.roll(xi, 1), np.roll(yi, 1)
    crosses = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi)
    return bool(np.count_nonzero(crosses) % 2)


def _near_line(rings: list[np.ndarray], x: float, y: float, tolerance: float = HIT_TOLERANCE) -> bool:
    for ring in rings:
        if ring.shape[0] < 2:
            continue
        a, b = ring[:-1], ring[1:]
        if _min_segment_distance(a, b, x, y) <= tolerance:
            return True
    return False


def _min_segment_distance(a: np.ndarray, b: np.ndarray, x: float, y: float) -> float:
    ax, ay = a[:, 0], a[:, 1]
    dx, dy = b[:, 0] - ax, b[:, 1] - ay
    length2 = dx * dx + dy * dy
    length2 = np.where(length2 == 0, 1e-12, length2)
    t = np.clip(((x - ax) * dx + (y - ay) * dy) / length2, 0.0, 1.0)
    cx, cy = ax + t * dx, ay + t * dy
    return float(np.sqrt((x - cx) ** 2 + (y - cy) ** 2).min())


def _near_point(rings: list[np.ndarray], x: float, y: float, reach: float) -> bool:
    for ring in rings:
        if ring.shape[0] == 0:
            continue
        d2 = (ring[:, 0] - x) ** 2 + (ring[:, 1] - y) ** 2
        if float(d2.min()) <= reach * reach:
            return True
    return False
