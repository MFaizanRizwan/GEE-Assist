"""The gallery of a project's result maps (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.widgets.result_gallery import COLUMNS, ResultGallery  # noqa: E402

app = QApplication.instance() or QApplication([])

MAPS = [(f"C:/p/analysis/r{n}.tif", f"Vegetation · NDVI {n}", f"1{n} Nov 2026, 10:00") for n in range(5)]


def _click(widget) -> None:
    point = QPointF(5, 5)
    for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(widget, QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton,
                                                   Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def _image(width=300, height=200) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#3a9b5c"))
    return image


def test_each_map_gets_a_tile_in_rows_of_three_with_its_title_and_date():
    gallery = ResultGallery()
    gallery.set_maps(MAPS)
    assert list(gallery.tiles) == [path for path, _, _ in MAPS]
    tile = gallery.tiles[MAPS[0][0]]
    assert tile.title.text() == "Vegetation · NDVI 0" and tile.subtitle.text() == "10 Nov 2026, 10:00"
    grid = gallery.layout()
    positions = [grid.getItemPosition(grid.indexOf(t))[:2] for t in gallery.tiles.values()]
    assert positions == [(i // COLUMNS, i % COLUMNS) for i in range(5)]
    assert tile.title.alignment() & Qt.AlignmentFlag.AlignLeft


def test_pictures_fill_in_as_they_are_drawn():
    gallery = ResultGallery()
    gallery.set_maps(MAPS[:2])
    first, second = gallery.tiles.values()
    assert not first.has_picture() and first.picture.text() == "Drawing…"
    gallery.set_picture(MAPS[0][0], _image())
    gallery.set_picture(MAPS[1][0], None)  # could not be drawn
    gallery.set_picture("C:/elsewhere.tif", _image())  # not in the gallery: ignored
    assert first.has_picture() and not second.has_picture() and second.picture.text() == "No picture"
    picture = first.picture.pixmap()
    assert picture.width() <= first.picture.width() and picture.height() <= first.picture.height()


def test_clicking_a_map_asks_to_open_it():
    gallery = ResultGallery()
    gallery.set_maps(MAPS[:2])
    opened = []
    gallery.open_requested.connect(opened.append)
    _click(gallery.tiles[MAPS[1][0]])
    assert opened == [MAPS[1][0]]


def test_setting_the_maps_again_replaces_them():
    gallery = ResultGallery()
    gallery.set_maps(MAPS)
    gallery.set_maps(MAPS[:1])
    assert list(gallery.tiles) == [MAPS[0][0]] and gallery.layout().count() == 1


def test_all_text_in_the_gallery_is_left_aligned():
    from PyQt6.QtWidgets import QLabel

    gallery = ResultGallery()
    gallery.set_maps(MAPS[:2])
    gallery.set_picture(MAPS[1][0], None)
    for label in gallery.findChildren(QLabel):
        if label.text():
            assert label.alignment() & Qt.AlignmentFlag.AlignLeft, label.text()
