"""Design a printable map and export it as PDF (IDW and DEM pages).

A page (A4, A3 or Letter, portrait or landscape) holds the map frame (the result, with the
boundary layer and the sample points drawn as vectors over it) and the map elements: a
title, a north arrow, a distance scale bar and a legend. Each element can be shown or
hidden and dragged anywhere on the page; the title is edited in place (double-click it) or
in the panel. Export paints the page into a PDF: lines and text stay vector, sharp at any
zoom.

The map keeps its true shape: a map in degrees is widened by the cosine of its latitude,
as the ground is. The scale bar is worked out from the frame's ground scale.
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
    QImage,
    QLinearGradient,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
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
    QVBoxLayout,
    QWidget,
)

from frontend import theme, theming

PAGE_SIZES = {"A4": QPageSize.PageSizeId.A4, "A3": QPageSize.PageSizeId.A3, "Letter": QPageSize.PageSizeId.Letter}
MARGIN = 36.0          # page margin, points
INK = QColor("#1C2B26")


@dataclass
class MapLayoutSpec:
    """What goes on the page. Coordinates (extent, rings, points) are in the raster's CRS."""

    title: str
    image: QImage
    extent: tuple[float, float, float, float]           # west, south, east, north
    geographic: bool = True                             # degrees (else metres)
    legend_title: str = ""
    legend: tuple = ()                                  # ("scale", colours, low, high) or ("classes", [(label, colour)])
    boundary_rings: list = field(default_factory=list)  # [[(x, y), ...], ...]
    selected_rings: list = field(default_factory=list)  # drawn highlighted
    points: list = field(default_factory=list)          # [(x, y), ...]
    note: str = ""                                      # a line under the map (source, date, method)
    load_boundary: Callable[[str], list] | None = None  # a shapefile path -> its rings in the CRS (DEM page)


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
    return f"{metres / 1000:g} km" if metres >= 1000 else f"{metres:g} m"


# ================================================================ page items
class _Movable:
    def make_movable(self) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(10)


class MapFrameItem(QGraphicsItem):
    """The map: the raster in its true shape, centred in the frame, with vectors over it."""

    def __init__(self, spec: MapLayoutSpec, rect: QRectF):
        super().__init__()
        self.spec = spec
        self.frame = rect
        self.show_boundaries = True
        self.show_points = True
        self._layout()

    def _layout(self) -> None:
        width_m, height_m = ground_size(self.spec.extent, self.spec.geographic)
        aspect = width_m / height_m if height_m else 1.0
        inner = self.frame.adjusted(6, 6, -6, -6)
        if inner.width() / inner.height() > aspect:
            w, h = inner.height() * aspect, inner.height()
        else:
            w, h = inner.width(), inner.width() / aspect
        self.map_rect = QRectF(inner.center().x() - w / 2, inner.center().y() - h / 2, w, h)
        self.metres_per_point = width_m / w if w else 0.0
        self._boundary_path = self._path(self.spec.boundary_rings)
        self._selected_path = self._path(self.spec.selected_rings)

    def to_page(self, x: float, y: float) -> QPointF:
        west, south, east, north = self.spec.extent
        r = self.map_rect
        return QPointF(r.left() + (x - west) / ((east - west) or 1) * r.width(),
                       r.top() + (north - y) / ((north - south) or 1) * r.height())

    def _path(self, rings) -> QPainterPath:
        path = QPainterPath()
        for ring in rings:
            if len(ring) < 2:
                continue
            path.addPolygon(QPolygonF([self.to_page(x, y) for x, y in ring]))
        return path

    def set_boundaries(self, rings) -> None:
        self.spec.boundary_rings = rings
        self._boundary_path = self._path(rings)
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt API)
        return self.frame

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipRect(self.frame)
        painter.fillRect(self.frame, QColor("#FFFFFF"))
        painter.drawImage(self.map_rect, self.spec.image)
        if self.show_boundaries and not self._boundary_path.isEmpty():
            pen = QPen(QColor("#1F2A44"), 0.6)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._boundary_path)
        if self.show_boundaries and not self._selected_path.isEmpty():
            painter.setPen(QPen(QColor("#0077B6"), 1.6))
            painter.drawPath(self._selected_path)
        if self.show_points and self.spec.points:
            painter.setPen(QPen(QColor("#FFFFFF"), 0.6))
            painter.setBrush(QColor("#111111"))
            for x, y in self.spec.points:
                painter.drawEllipse(self.to_page(x, y), 1.8, 1.8)
        painter.setClipping(False)
        painter.setPen(QPen(INK, 0.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.frame)
        painter.restore()


class NorthArrowItem(QGraphicsItem, _Movable):
    SIZE = 34.0

    def __init__(self):
        super().__init__()
        self.make_movable()

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-self.SIZE / 2 - 2, -self.SIZE * 0.45 - 14, self.SIZE + 4, self.SIZE * 1.05 + 14)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SIZE
        left = QPolygonF([QPointF(0, -s * 0.45), QPointF(-s * 0.22, s * 0.45), QPointF(0, s * 0.28)])
        right = QPolygonF([QPointF(0, -s * 0.45), QPointF(s * 0.22, s * 0.45), QPointF(0, s * 0.28)])
        painter.setPen(QPen(INK, 0.8))
        painter.setBrush(INK)
        painter.drawPolygon(left)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPolygon(right)
        painter.setFont(page_font(11, bold=True))
        painter.setPen(INK)
        painter.drawText(QRectF(-12, -s * 0.45 - 15, 24, 14), Qt.AlignmentFlag.AlignCenter, "N")


class ScaleBarItem(QGraphicsItem, _Movable):
    """Two-tone segments over a round ground distance, sized from the map frame's scale."""

    TARGET = 120.0   # points: the bar's length is the largest round distance not longer

    def __init__(self, frame: MapFrameItem):
        super().__init__()
        self.frame = frame
        self.make_movable()

    def distance(self) -> tuple[float, float]:
        """(metres, length in points)"""
        mpp = self.frame.metres_per_point
        metres = nice_distance(mpp * self.TARGET) if mpp else 0.0
        return metres, (metres / mpp if mpp else 0.0)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-4, -16, self.TARGET + 30, 34)

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
        painter.drawText(QRectF(-10, 6, 20, 10), Qt.AlignmentFlag.AlignCenter, "0")
        painter.drawText(QRectF(length / 2 - 30, 6, 60, 10), Qt.AlignmentFlag.AlignCenter, distance_text(metres / 2))
        painter.drawText(QRectF(length - 30, 6, 60, 10), Qt.AlignmentFlag.AlignCenter, distance_text(metres))


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
        bold = page_font(8, bold=True)
        plain = page_font(8)
        painter.setFont(bold)
        painter.setPen(INK)
        painter.drawText(QRectF(8, 6, self.WIDTH - 16, 14), Qt.AlignmentFlag.AlignLeft, self.title)
        painter.setFont(plain)
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


def page_font(size: float, bold: bool = False) -> QFont:
    """A font sized in page units (the scene's points). Point sizes would be scaled twice when
    the page is painted into a 300-dpi PDF (once for the device, once for the page), so the
    hand-painted elements (legend, north arrow, scale bar) would print several times too big."""
    font = QFont(theme.SANS)
    font.setPixelSize(max(1, round(size)))
    font.setBold(bold)
    return font


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
        self.resize(1180, 820)
        self.spec = spec
        self.exported: str = ""

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
        self.toggles: dict[str, QCheckBox] = {}
        for key, label in (("title", "Title"), ("north", "North arrow"), ("scale", "Scale bar"),
                           ("legend", "Legend"), ("boundaries", "Boundary layer"), ("points", "Sample points"),
                           ("note", "Note under the map")):
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self._apply_toggles)
            self.toggles[key] = box
        self.toggles["points"].setVisible(bool(spec.points))
        self.boundary_button = QPushButton("Add boundary layer…", objectName="SecondaryButton")
        self.boundary_button.setVisible(spec.load_boundary is not None)
        self.reset_button = QPushButton("Reset positions", objectName="SecondaryButton")
        self.export_button = QPushButton("Export PDF…", objectName="PrimaryButton")
        self.close_button = QPushButton("Close", objectName="SecondaryButton")
        self.message = QLabel(objectName="Muted")
        self.message.setWordWrap(True)

        panel = QVBoxLayout()
        panel.setSpacing(8)
        panel.addWidget(QLabel("Title", objectName="Muted"))
        panel.addWidget(self.title_edit)
        row = QHBoxLayout()
        row.addWidget(self.page_box)
        row.addWidget(self.orientation_box)
        panel.addWidget(QLabel("Page", objectName="Muted"))
        panel.addLayout(row)
        panel.addSpacing(6)
        panel.addWidget(QLabel("Show on the page", objectName="Muted"))
        for box in self.toggles.values():
            panel.addWidget(box)
        panel.addWidget(self.boundary_button)
        panel.addSpacing(6)
        hint = QLabel("Drag the title, north arrow, scale bar and legend to place them. Double-click the title to "
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
        side.setFixedWidth(250)

        layout = QHBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addWidget(side)
        theming.styled(self, lambda: f"QDialog {{ background: {theme.WHITE}; }}")

        self.title_edit.textChanged.connect(lambda text: self.title_item.setPlainText(text))
        self.page_box.currentIndexChanged.connect(lambda *_: self.build())
        self.orientation_box.currentIndexChanged.connect(lambda *_: self.build())
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
        page = self.page_rect()
        self.scene.setSceneRect(page.adjusted(-20, -20, 20, 20))
        self.page_item = self.scene.addRect(page, QPen(QColor("#7A8580"), 0.5), QBrush(QColor("#FFFFFF")))
        self.page_item.setZValue(-10)
        top = MARGIN + 34
        bottom = page.height() - MARGIN - 18
        frame = QRectF(MARGIN, top, page.width() - 2 * MARGIN, bottom - top)
        self.frame_item = MapFrameItem(self.spec, frame)
        self.scene.addItem(self.frame_item)

        self.title_item = _Title(self.title_edit.text())
        self.scene.addItem(self.title_item)
        width = self.title_item.boundingRect().width()
        self.title_item.setPos(page.width() / 2 - width / 2, MARGIN - 4)

        self.north_item = NorthArrowItem()
        self.scene.addItem(self.north_item)
        self.north_item.setPos(frame.right() - 30, frame.top() + 36)

        self.scale_item = ScaleBarItem(self.frame_item)
        self.scene.addItem(self.scale_item)
        self.scale_item.setPos(frame.right() - ScaleBarItem.TARGET - 30, frame.bottom() - 28)

        self.legend_item = LegendItem(self.spec.legend_title, self.spec.legend)
        self.scene.addItem(self.legend_item)
        self.legend_item.setPos(frame.left() + 12, frame.bottom() - self.legend_item.boundingRect().height() - 12)

        self.note_item = self.scene.addText(self.spec.note)
        font = QFont(theme.SANS)
        font.setPointSizeF(7)
        self.note_item.setFont(font)
        self.note_item.setDefaultTextColor(QColor("#55625D"))
        self.note_item.setPos(MARGIN, frame.bottom() + 1)
        self._apply_toggles()
        self.view.fitInView(page.adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)

    def _apply_toggles(self, *_args) -> None:
        if not hasattr(self, "frame_item"):
            return
        shown = {key: box.isChecked() for key, box in self.toggles.items()}
        self.title_item.setVisible(shown["title"])
        self.north_item.setVisible(shown["north"])
        self.scale_item.setVisible(shown["scale"])
        self.legend_item.setVisible(shown["legend"] and bool(self.spec.legend))
        self.note_item.setVisible(shown["note"] and bool(self.spec.note))
        self.frame_item.show_boundaries = shown["boundaries"]
        self.frame_item.show_points = shown["points"]
        self.frame_item.update()

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
        self.scene.clearSelection()
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
