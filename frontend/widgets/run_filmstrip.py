"""A filmstrip of the open project's saved analysis results, under the Analysis page's map.

Each frame is the result's map picture with its name and key figure; clicking one opens its
GeoTIFF in the viewer. The pictures are drawn in the background by the caller (the same way the
dashboard draws its result maps) and handed in with ``set_picture``. Styled by the page it sits
on (``QFrame#FilmTile``), so it follows every layout and theme.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

PICTURE_W, PICTURE_H = 176, 74
TILE_W = PICTURE_W + 16


class FilmTile(QFrame):
    """One saved result: its map picture (a placeholder until drawn) and a one-line caption."""

    clicked = pyqtSignal(str)  # the result GeoTIFF

    def __init__(self, path: str, caption: str, tooltip: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self.setObjectName("FilmTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{tooltip}\nOpen it in the viewer")
        self.setFixedWidth(TILE_W)
        self.picture = QLabel("Drawing…", objectName="FilmPicture")
        self.picture.setFixedSize(PICTURE_W, PICTURE_H)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption = QLabel(caption, objectName="FilmCaption")
        self.caption.setMaximumWidth(PICTURE_W)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.picture)
        layout.addWidget(self.caption)

    def set_picture(self, image: QImage | None) -> None:
        if image is None or image.isNull():
            self.picture.setText("No picture")
            return
        self.picture.setPixmap(QPixmap.fromImage(image).scaled(
            self.picture.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.path)
        super().mouseReleaseEvent(event)


class RunFilmstrip(QWidget):
    """Saved results of the project, newest first, in one horizontally scrolling row."""

    open_requested = pyqtSignal(str)  # a result GeoTIFF to open in the viewer

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("RunFilmstrip")
        self.tiles: dict[str, FilmTile] = {}
        self.empty = QLabel("Saved results of this project appear here, newest first. Click one to open it "
                            "in the viewer.", objectName="Muted")
        self.empty.setWordWrap(True)
        row_host = QWidget(objectName="FilmRow")
        self._row = QHBoxLayout(row_host)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(10)
        self._row.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(row_host)
        self._scroll.setFixedHeight(PICTURE_H + 58)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.empty)
        layout.addWidget(self._scroll)
        self.set_runs([])

    def set_runs(self, runs: list[tuple[str, str, str]]) -> None:
        """``runs``: (GeoTIFF path, caption, tooltip), newest first."""
        for tile in self.tiles.values():
            self._row.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()
        self.tiles = {}
        for path, caption, tooltip in runs:
            tile = FilmTile(path, caption, tooltip)
            tile.clicked.connect(self.open_requested)
            self._row.insertWidget(self._row.count() - 1, tile)  # before the closing stretch
            self.tiles[path] = tile
        self.empty.setVisible(not runs)
        self._scroll.setVisible(bool(runs))

    def set_picture(self, path: str, image: QImage | None) -> None:
        tile = self.tiles.get(path)
        if tile is not None:
            tile.set_picture(image)
