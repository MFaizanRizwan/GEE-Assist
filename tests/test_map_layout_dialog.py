"""The PDF map designer: north-arrow styles, a stretchable scale bar, and the country layout."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from frontend.views.map_layout_dialog import (  # noqa: E402
    NORTH_ARROWS,
    MapLayoutDialog,
    MapLayoutSpec,
    NorthArrowItem,
    north_arrow_icon,
)
from frontend.widgets.raster_canvas import rgba_to_image  # noqa: E402

CITY = [(73.0, 31.3), (73.0, 31.6), (73.3, 31.6), (73.3, 31.3), (73.0, 31.3)]
COUNTRY = [(61.0, 24.0), (61.0, 37.0), (77.0, 37.0), (77.0, 24.0), (61.0, 24.0)]


def _spec(context=True):
    rgba = np.zeros((40, 40, 4), np.uint8)
    rgba[..., 0], rgba[..., 3] = 220, 255
    return MapLayoutSpec("pH", rgba_to_image(rgba), (73.0, 31.3, 73.3, 31.6), True, "pH",
                         ("classes", [("6 – 7", "#FFFFB2"), ("7 – 8", "#BD0026")]), [CITY], [CITY],
                         [(73.1, 31.4)], "note",
                         context_rings=[COUNTRY, CITY] if context else [],
                         context_extent=(61.0, 24.0, 77.0, 37.0) if context else None)


@pytest.mark.parametrize("style", list(NORTH_ARROWS))
def test_every_north_arrow_style_draws_and_resizes(style):
    item = NorthArrowItem(style, 34)
    image = QImage(200, 200, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.translate(100, 100)
    item.paint(painter, None)
    painter.end()
    assert image.copy(60, 60, 80, 80) != QImage(80, 80, QImage.Format.Format_ARGB32)   # something was drawn
    assert not north_arrow_icon(style).isNull()
    item.resize_to(QPointF(44, 30))                 # dragging the handle out
    assert item.size == pytest.approx(80, abs=0.5)
    item.set_size(500)
    assert item.size == 160                         # within limits


def test_the_scale_bar_stretches_and_shows_the_distance_it_spans():
    dialog = MapLayoutDialog(_spec(context=False))
    bar = dialog.scale_item
    metres, length = bar.distance()
    assert metres > 0
    bar.resize_to(QPointF(length * 1.5, 2))         # stretched by half again
    stretched, new_length = bar.distance()
    assert new_length == pytest.approx(length * 1.5) and stretched == pytest.approx(metres * 1.5)
    bar.round_length()
    rounded = bar.distance()[0]
    assert str(int(rounded)).rstrip("0") in ("1", "2", "5")   # 1, 2 or 5 × 10ⁿ
    dialog.deleteLater()


def test_the_country_layout_shows_the_area_boxed_and_magnified(tmp_path):
    without = MapLayoutDialog(_spec(context=False))
    assert not without.layout_box.isEnabled()                    # no boundary layer: area only
    without.deleteLater()
    dialog = MapLayoutDialog(_spec())
    dialog.layout_box.setCurrentIndex(dialog.layout_box.findData("locator"))
    locator, detail = dialog.overview_item, dialog.frame_item
    assert locator is not None and locator.extent == (61.0, 24.0, 77.0, 37.0)
    assert detail.extent == (73.0, 31.3, 73.3, 31.6)
    assert locator.box.width() < locator.map_rect.width() / 10   # the city is small on the country map
    assert detail.metres_per_point < locator.metres_per_point / 10   # and magnified beside it
    # the scale bar measures the map it is put on
    dialog.scale_item.setPos(detail.map_rect.left() + 10, detail.map_rect.bottom() - 20)
    near = dialog.scale_item.distance()[0]
    dialog.scale_item.setPos(locator.map_rect.left() + 10, locator.map_rect.bottom() - 20)
    assert dialog.scale_item.distance()[0] > near * 10
    dialog.arrow_box.setCurrentIndex(dialog.arrow_box.findData("rose"))
    assert dialog.north_item.style == "rose"
    dialog.arrow_size.setValue(70)
    assert dialog.north_item.size == 70
    pdf = dialog.export(str(tmp_path / "country"))
    assert open(pdf, "rb").read(4) == b"%PDF"
    dialog.deleteLater()


def test_the_mouse_resizes_and_moves_the_arrow_and_stretches_the_scale_bar():
    """Real mouse events through the view (hover, press, drag, release): the path that crashed
    with "'super' object has no attribute 'hoverMoveEvent'"."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    dialog = MapLayoutDialog(_spec())
    dialog.resize(1200, 820)
    dialog.show()
    QTest.qWait(50)
    view, viewport = dialog.view, dialog.view.viewport()

    def at(item, point: QPointF) -> QPoint:
        return view.mapFromScene(item.mapToScene(point))

    def drag(start: QPoint, end: QPoint) -> None:
        QTest.mouseMove(viewport, start)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in range(1, 6):
            QTest.mouseMove(viewport, start + (end - start) * step / 5)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        QTest.qWait(20)

    arrow = dialog.north_item
    QTest.mouseMove(viewport, at(arrow, QPointF(0, 0)))                  # hovering: no error
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=at(arrow, QPointF(0, 0)))
    assert arrow.isSelected()
    size = arrow.size
    handle = arrow.handle_rect().center()
    drag(at(arrow, handle), at(arrow, handle + QPointF(30, 30)))         # the corner handle, outwards
    assert arrow.size > size + 20
    position = arrow.pos()
    drag(at(arrow, QPointF(0, 0)), at(arrow, QPointF(0, 0)) + QPoint(-120, 60))   # the body: moved
    assert arrow.pos().x() < position.x() - 50 and arrow.size > size + 20

    bar = dialog.scale_item
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=at(bar, QPointF(bar.length / 3, 2)))
    assert bar.isSelected()
    metres, length = bar.distance()
    end = bar.handle_rect().center()
    drag(at(bar, end), at(bar, end + QPointF(60, 0)))                    # its right end, stretched
    assert bar.length > length + 30 and bar.distance()[0] > metres * 1.3
    dialog.deleteLater()
