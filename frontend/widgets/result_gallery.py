"""A gallery of a project's result maps: a picture of each saved analysis result, with what it is
and when it was made underneath (left-aligned). Clicking a picture asks to open its GeoTIFF.

Pictures are added as they are drawn (``set_picture``), so the gallery can show its tiles at once
and fill them in as the background work finishes.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from frontend import theme
from frontend import theming

THUMBNAIL = 220                                 # longer side of a picture, in pixels
COLUMNS = 3

def _stylesheet():
    return f"""
QFrame#ResultMap {{ background: {theme.FOAM}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}
QFrame#ResultMap:hover {{ border-color: {theme.LEAF}; }}
QLabel#ResultMapPicture {{ background: {theme.WHITE}; border-radius: 6px; color: {theme.MUTED}; }}
"""


class ResultMapTile(QFrame):
    """One result map: its picture (a placeholder until drawn), its title and its date."""

    clicked = pyqtSignal(str)  # the result GeoTIFF

    def __init__(self, path: str, title: str, subtitle: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self.setObjectName("ResultMap")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Open {path} in the viewer")
        self.picture = QLabel("Drawing…", objectName="ResultMapPicture")
        self.picture.setFixedSize(THUMBNAIL, THUMBNAIL * 3 // 4)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # as all dashboard text
        self.title = QLabel(title, objectName="ItemTitle")
        self.subtitle = QLabel(subtitle, objectName="ItemMeta")
        for label in (self.title, self.subtitle):
            label.setWordWrap(True)
            label.setMaximumWidth(THUMBNAIL)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        layout.addWidget(self.picture)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addStretch(1)

    def set_picture(self, image: QImage | None) -> None:
        """The drawn map, fitted in the tile; None when it could not be drawn."""
        if image is None or image.isNull():
            self.picture.setText("No picture")
            return
        box = self.picture.size()
        self.picture.setPixmap(QPixmap.fromImage(image).scaled(
            box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def has_picture(self) -> bool:
        pixmap = self.picture.pixmap()
        return pixmap is not None and not pixmap.isNull()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.path)
        super().mouseReleaseEvent(event)


class ResultGallery(QWidget):
    """Result map tiles in rows of three, from the left."""

    open_requested = pyqtSignal(str)  # a result GeoTIFF to open in the viewer

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        theming.styled(self, _stylesheet)
        self.tiles: dict[str, ResultMapTile] = {}
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    def set_maps(self, maps: list[tuple[str, str, str]]) -> None:
        """(GeoTIFF, title, subtitle) of each map, in order; their pictures are added with ``set_picture``."""
        for tile in self.tiles.values():
            self._grid.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()
        self.tiles = {}
        for index, (path, title, subtitle) in enumerate(maps):
            tile = ResultMapTile(path, title, subtitle)
            tile.clicked.connect(self.open_requested)
            self._grid.addWidget(tile, index // COLUMNS, index % COLUMNS)
            self.tiles[path] = tile

    def set_picture(self, path: str, image: QImage | None) -> None:
        tile = self.tiles.get(path)
        if tile is not None:
            tile.set_picture(image)
