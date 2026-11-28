"""Draws a vector map (a loaded shapefile) with mouse-wheel zoom, drag-to-pan and
double-click-to-fit, like a desktop GIS canvas.

Everything is in WGS84 longitude/latitude; the canvas keeps a simple fit transform from
geographic coordinates to screen pixels (latitude grows upward, so the y axis is flipped).
It reports the feature under the pointer (``feature_hovered``) and the one clicked
(``feature_clicked``) by their index in the layer.

Why it is drawn the way it is
-----------------------------
Admin-boundary and OpenStreetMap layers have hundreds of thousands of vertices. Painting
them (antialiased, filled) takes 100-300 ms, and Qt paints on one core only: PyQt holds
Python's lock while it paints, so even several threads paint no faster. Repainting the
shapes on every mouse move is what made dragging lag while the CPU looked idle.

So the shapes are painted once into a *layer picture* a little larger than the view, and
every frame just draws that picture, shifted (panning) or stretched (zooming, as a quick
preview): about a millisecond. When the view settles, a sharp picture for the new view is
painted on a worker thread (the UI stays responsive: the lock is handed back between
shapes) and swapped in. Only the selected feature is drawn live, on top.

The pointer's feature is found in longitude/latitude against the original geometry, so
hovering never needs the screen geometry rebuilt.
"""

from __future__ import annotations

import threading

import numpy as np
from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from backend.dto.vector_dto import MULTIPOINT, POINT, POLYGON, POLYLINE, VectorLayerDTO
from frontend import theme

ZOOM_STEP = 1.25
MAX_ZOOM = 5000.0
MIN_ZOOM = 1.0
MARGIN = 24             # screen pixels kept around the layer when fitted
HIT_TOLERANCE = 6       # screen pixels: how close the pointer must be to pick a line or point
PICTURE_MARGIN = 0.5    # the layer picture reaches this fraction of the view beyond each edge
RENDER_DELAY_MS = 90    # repaint the picture sharply once the view has been still this long


class _Cached:
    """Screen-space geometry of one feature (for painting it)."""

    __slots__ = ("kind", "paths", "polys", "rings", "bbox")

    def __init__(self, kind: str):
        self.kind = kind
        # polygons: one filled path per outer ring with its holes (even-odd). Kept apart so a
        # country of 400 islands is 400 short paint calls, not one long one: the worker thread
        # hands Python's lock back between them and the UI never waits long.
        self.paths: list[QPainterPath] = []
        self.polys: list[QPolygonF] = []               # polylines
        self.rings: list[np.ndarray] = []              # decimated screen coords (M, 2)
        self.bbox = (0.0, 0.0, 0.0, 0.0)               # screen bounds


class _Style:
    """Pens and brushes for one picture, made once (not per feature)."""

    def __init__(self, fill: QColor, outline: QColor, point_size: int):
        self.fill = QBrush(fill)
        self.point_fill = QBrush(QColor(fill.red(), fill.green(), fill.blue()))
        self.pen = QPen(outline, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        self.point_pen = QPen(outline, 1.2)
        self.radius = point_size / 2


class _Picture:
    """A painted layer picture and the view it was painted for."""

    def __init__(self, image: QImage, transform: tuple[float, float, float], origin: QPointF, key: tuple):
        self.image = image
        self.transform = transform   # (scale, ox, oy) it was painted with
        self.origin = origin         # its top-left in widget coordinates, for that transform
        self.key = key               # (width, height, pixel ratio, style version)


class _Relay(QObject):
    """Brings a picture painted on the worker thread back to the UI thread (queued signal)."""

    done = pyqtSignal(int, object)   # generation, _Picture


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
        self._bounds = np.zeros((0, 4))                 # per feature: lon/lat bounds (for culling, picking)
        self._groups: list[list[tuple]] = []            # per polygon: (bounds, [outer, holes...]) per island
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._selected = -1
        self._hover = -1
        self._dragging = False
        self._drag_from = QPointF()
        self._pan_from = QPointF()
        self._moved = False
        self._fill = QColor(theme.OCEAN)
        self._fill.setAlpha(90)
        self._outline = QColor(theme.OCEAN)
        self._point_size = 7
        # ---- the layer picture
        self._picture: _Picture | None = None
        self._style_version = 0             # bumped when the look changes: the picture is redrawn
        self._generation = 0                # the newest picture asked for; older ones are dropped
        self._rendering = False
        self._relay = _Relay()
        self._relay.done.connect(self._on_rendered)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(RENDER_DELAY_MS)
        self._render_timer.timeout.connect(self._render_in_background)
        # ---- the selected feature's screen geometry, drawn live on top: (key, _Cached)
        self._selected_cache: tuple | None = None

    # ------------------------------------------------------------- data & style
    def set_layer(self, layer: VectorLayerDTO | None) -> None:
        self._layer = layer
        self._selected = -1
        self._hover = -1
        self._geo = []
        if layer is not None:
            for feature in layer.features:
                self._geo.append([np.asarray(ring, dtype="float64").reshape(-1, 2) for ring in feature.parts if ring])
            self._bounds = np.array([f.bounds for f in layer.features], dtype="float64").reshape(-1, 4)
            self._groups = [_island_groups(rings) if f.kind == POLYGON else []
                            for rings, f in zip(self._geo, layer.features)]
        else:
            self._bounds = np.zeros((0, 4))
            self._groups = []
        self._restyle()
        self.fit()

    def set_colours(self, fill: QColor, outline: QColor) -> None:
        self._fill, self._outline = QColor(fill), QColor(outline)
        self._restyle()

    def set_point_size(self, size: int) -> None:
        self._point_size = max(2, int(size))
        self._restyle()

    def _restyle(self) -> None:
        """The look or the data changed: the picture must be painted again (now, at next paint)."""
        self._style_version += 1
        self._generation += 1          # a picture being painted for the old look is dropped
        self._picture = None
        self._selected_cache = None
        self.update()

    def set_selected(self, index: int) -> None:
        if index != self._selected:
            self._selected = index
            self._selected_cache = None
            self.update()

    def selected(self) -> int:
        return self._selected

    # ------------------------------------------------------------- view
    def fit(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._view_changed()

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
        self._selected_cache = None
        self._view_changed()

    def _view_changed(self) -> None:
        """Zoom, pan or size changed: show the current picture moved/stretched at once, and
        paint a sharp one for this view when it settles (unless the picture still fits it)."""
        if self._picture is not None and not self._dragging and not self._picture_fits():
            self._render_timer.start()
        self.update()

    def _picture_fits(self) -> bool:
        """The picture is sharp for this view and still covers it (panning within its margin)."""
        picture = self._picture
        if picture is None or picture.key != self._picture_key():
            return False
        scale, ox, oy = self._transform(self._pan)
        s0, ox0, oy0 = picture.transform
        if abs(scale / s0 - 1.0) > 1e-9:
            return False
        dx, dy = ox - ox0, oy - oy0
        image_w = picture.image.width() / picture.image.devicePixelRatio()
        image_h = picture.image.height() / picture.image.devicePixelRatio()
        left, top = picture.origin.x() + dx, picture.origin.y() + dy
        return left <= 0 and top <= 0 and left + image_w >= self.width() and top + image_h >= self.height()

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

    # ------------------------------------------------------------- the layer picture
    def _picture_key(self) -> tuple:
        return (self.width(), self.height(), round(self.devicePixelRatioF(), 3), self._style_version)

    def _render_job(self):
        """Everything needed to paint the picture for the current view, as a function that
        can run on any thread (it touches no widget)."""
        width, height, ratio = self.width(), self.height(), self.devicePixelRatioF()
        mx, my = int(width * PICTURE_MARGIN), int(height * PICTURE_MARGIN)
        transform = self._transform(self._pan)
        scale, ox, oy = transform
        # the features that reach the picture, from their lon/lat bounds (no geometry needed)
        bounds = self._bounds
        left, right = (-mx - ox) / scale, (width + mx - ox) / scale
        top, bottom = (oy + my) / scale, (oy - height - my) / scale        # latitudes
        visible = np.nonzero((bounds[:, 2] >= left) & (bounds[:, 0] <= right)
                             & (bounds[:, 3] >= bottom) & (bounds[:, 1] <= top))[0] if len(bounds) else []
        geo, kinds = self._geo, [f.kind for f in self._layer.features]
        style = _Style(self._fill, self._outline, self._point_size)
        key = self._picture_key()

        def paint() -> _Picture:
            image = QImage(max(1, round((width + 2 * mx) * ratio)), max(1, round((height + 2 * my) * ratio)),
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(mx, my)
            for index in visible:
                cached = _cache_feature(geo[index], kinds[index], scale, ox, oy)
                _draw_feature(painter, cached, style)
            painter.end()
            return _Picture(image, transform, QPointF(-mx, -my), key)

        return paint

    def _render_now(self) -> None:
        self._generation += 1
        self._picture = self._render_job()()

    def _render_in_background(self) -> None:
        if self._layer is None or self._dragging:
            return
        if self._rendering:           # one at a time: ask again once this one is done
            self._render_timer.start()
            return
        self._generation += 1
        generation, job = self._generation, self._render_job()
        self._rendering = True

        def run() -> None:
            try:
                picture = job()
            except Exception:  # noqa: BLE001 - a failed picture keeps the old one
                picture = None
            self._relay.done.emit(generation, picture)

        threading.Thread(target=run, name="vector-picture", daemon=True).start()

    def _on_rendered(self, generation: int, picture: _Picture | None) -> None:
        self._rendering = False
        if picture is not None and generation == self._generation and picture.key == self._picture_key():
            self._picture = picture
            self.update()
        if self._picture is not None and not self._dragging and not self._picture_fits():
            self._render_timer.start()   # the view moved on while it was painted

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.FIELD_BG))
        if self._layer is None or not self._geo:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open a shapefile to see it here.")
            return
        if self._picture is None or self._picture.key[3] != self._style_version:
            self._render_now()            # first picture (or a new look): paint it straight away
        elif self._picture.key != self._picture_key() and not self._render_timer.isActive():
            self._render_timer.start()    # resized: stretch this one meanwhile
        picture = self._picture
        scale, ox, oy = self._transform(self._pan)
        s0, ox0, oy0 = picture.transform
        ratio = scale / s0
        painter.save()
        # picture coordinates (the view it was painted for) -> this view
        painter.translate(ox - ox0 * ratio, oy - oy0 * ratio)
        painter.scale(ratio, ratio)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, abs(ratio - 1) > 1e-9)
        painter.drawImage(picture.origin, picture.image)
        painter.restore()
        if 0 <= self._selected < len(self._geo):
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_selected(painter)

    def _draw_selected(self, painter: QPainter) -> None:
        """The selected feature, highlighted, drawn live over the picture (cached per zoom)."""
        scale, ox, oy = self._transform(self._pan)
        key = (self._selected, self.width(), self.height(), round(self._zoom, 9))
        if self._selected_cache is None or self._selected_cache[0] != key:
            cached = _cache_feature(self._geo[self._selected], self._layer.features[self._selected].kind,
                                    scale, ox, oy)
            self._selected_cache = (key, cached, QPointF(ox, oy))
        _key, cached, built_at = self._selected_cache
        painter.save()
        painter.translate(ox - built_at.x(), oy - built_at.y())
        pen = QPen(QColor(theme.LEAF), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        if cached.kind == POLYGON:
            fill = QColor(theme.MINT)
            fill.setAlpha(160)
            painter.setBrush(QBrush(fill))
            painter.setPen(pen)
            for path in cached.paths:
                painter.drawPath(path)
        elif cached.kind == POLYLINE:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            for polygon in cached.polys:
                painter.drawPolyline(polygon)
        else:
            radius = (self._point_size + 3) / 2
            painter.setPen(QPen(QColor(theme.LEAF), 1.2))
            painter.setBrush(QBrush(QColor(theme.LEAF)))
            for ring in cached.rings:
                for x, y in ring:
                    painter.drawEllipse(QPointF(float(x), float(y)), radius, radius)
        painter.restore()

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
        self._view_changed()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._moved = False
            self._drag_from = event.position()
            self._pan_from = QPointF(self._pan)
            self._render_timer.stop()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._dragging:
            delta = event.position() - self._drag_from
            if abs(delta.x()) + abs(delta.y()) > 3:
                self._moved = True
            self._pan = self._pan_from + delta  # the picture just moves: nothing is repainted
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
            self._selected_cache = None
            self.feature_clicked.emit(index)
            self.update()
        else:
            self._view_changed()   # dragged past the picture's edge: paint the new area

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.fit()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._hover != -1:
            self._hover = -1
            self.feature_hovered.emit(-1)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._selected_cache = None
        self._view_changed()

    # ------------------------------------------------------------- hit testing
    def _feature_at(self, pos: QPointF) -> int:
        """The topmost feature under ``pos`` (widget coordinates), or -1. Tested in lon/lat
        against the original geometry, with the screen tolerance turned into degrees."""
        if self._layer is None or not self._geo:
            return -1
        scale = self._transform(self._pan)[0]
        if scale <= 0:
            return -1
        lon, lat = self._to_geo(pos.x(), pos.y())
        reach = HIT_TOLERANCE / scale
        point_reach = (self._point_size / 2 + HIT_TOLERANCE) / scale
        pad = reach + self._point_size / scale
        b = self._bounds
        near = np.nonzero((b[:, 0] - pad <= lon) & (lon <= b[:, 2] + pad)
                          & (b[:, 1] - pad <= lat) & (lat <= b[:, 3] + pad))[0]
        for index in near[::-1]:  # topmost first
            rings = self._geo[index]
            kind = self._layer.features[index].kind
            if kind == POLYGON and any(minx <= lon <= maxx and miny <= lat <= maxy and _in_polygon(group, lon, lat)
                                       for (minx, miny, maxx, maxy), group in self._groups[index]):
                return int(index)
            if kind == POLYLINE and _near_line(rings, lon, lat, reach):
                return int(index)
            if kind in (POINT, MULTIPOINT) and _near_point(rings, lon, lat, point_reach):
                return int(index)
        return -1


# ------------------------------------------------------------- painting helpers (any thread)
def _cache_feature(rings: list[np.ndarray], kind: str, scale: float, ox: float, oy: float) -> _Cached:
    """A feature's screen geometry for a transform: vertices on the same pixel dropped."""
    cached = _Cached(kind)
    bounds = [np.inf, np.inf, -np.inf, -np.inf]
    path: QPainterPath | None = None
    for ring in rings:
        if ring.shape[0] == 0:
            continue
        if kind == POLYGON and (path is None or _clockwise(ring)):
            # an outer ring (shapefiles wind them clockwise) starts a new path; holes follow it
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            cached.paths.append(path)
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
    cached.bbox = tuple(bounds) if np.isfinite(bounds[0]) else (0.0, 0.0, 0.0, 0.0)
    return cached


def _clockwise(ring: np.ndarray) -> bool:
    """Wound clockwise (lon right, lat up): a shapefile's outer ring; holes wind the other way."""
    x, y = ring[:, 0], ring[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) < 0


def _draw_feature(painter: QPainter, cached: _Cached, style: _Style) -> None:
    if cached.kind == POLYGON:
        painter.setBrush(style.fill)
        painter.setPen(style.pen)
        for path in cached.paths:
            painter.drawPath(path)
    elif cached.kind == POLYLINE:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(style.pen)
        for polygon in cached.polys:
            painter.drawPolyline(polygon)
    else:  # POINT / MULTIPOINT
        painter.setPen(style.point_pen)
        painter.setBrush(style.point_fill)
        radius = style.radius
        for ring in cached.rings:
            for x, y in ring:
                painter.drawEllipse(QPointF(float(x), float(y)), radius, radius)


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
    """A QPolygonF filled straight from the arrays (a point-by-point loop was most of the
    time spent building the geometry)."""
    polygon = QPolygonF()
    count = int(sx.size)
    if count == 0:
        return polygon
    polygon.resize(count)
    pointer = polygon.data()
    pointer.setsize(count * 16)                 # QPointF = two doubles
    view = np.frombuffer(pointer, dtype=np.float64).reshape(count, 2)
    view[:, 0] = sx
    view[:, 1] = sy
    return polygon


def _overlaps(bbox: tuple[float, float, float, float], rect: QRectF) -> bool:
    minx, miny, maxx, maxy = bbox
    return not (maxx < rect.left() or minx > rect.right() or maxy < rect.top() or miny > rect.bottom())


def _ring_groups(rings: list[np.ndarray]) -> list[list[np.ndarray]]:
    """A polygon's rings as [outer, hole, hole...] groups: each clockwise ring starts a group
    (an island of a many-island country), the anticlockwise ones after it are its holes."""
    groups: list[list[np.ndarray]] = []
    for ring in rings:
        if ring.shape[0] == 0:
            continue
        if not groups or _clockwise(ring):
            groups.append([ring])
        else:
            groups[-1].append(ring)
    return groups


def _island_groups(rings: list[np.ndarray]) -> list[tuple]:
    """``_ring_groups`` with each group's outer-ring bounds, worked out once per layer (the
    pointer then only tests the island it is over)."""
    out = []
    for group in _ring_groups(rings):
        outer = group[0]
        out.append(((float(outer[:, 0].min()), float(outer[:, 1].min()),
                     float(outer[:, 0].max()), float(outer[:, 1].max())), group))
    return out


def _in_polygon(rings: list[np.ndarray], x: float, y: float) -> bool:
    if not rings or not _ray_cast(rings[0], x, y):
        return False
    return not any(_ray_cast(hole, x, y) for hole in rings[1:])


def _ray_cast(ring: np.ndarray, x: float, y: float) -> bool:
    """Vectorised point-in-polygon (ray casting)."""
    n = ring.shape[0]
    if n < 3:
        return False
    xi, yi = ring[:, 0], ring[:, 1]
    xj, yj = np.roll(xi, 1), np.roll(yi, 1)
    with np.errstate(divide="ignore", invalid="ignore"):  # flat edges never count (masked below)
        crosses = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi) + xi)
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
    length2 = np.where(length2 == 0, 1e-300, length2)
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
