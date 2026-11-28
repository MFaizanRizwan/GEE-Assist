"""The vector map stays smooth: dragging and zooming move a painted picture instead of
repainting every shape, the sharp picture is painted off the UI thread, and the
picture still shows holes and picks the right feature."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.dto.vector_dto import POLYGON, VectorFeatureDTO, VectorLayerDTO  # noqa: E402
from frontend.widgets import vector_canvas  # noqa: E402
from frontend.widgets.vector_canvas import VectorCanvas  # noqa: E402

app = QApplication.instance() or QApplication([])

OUTER = ((0, 0), (0, 4), (4, 4), (4, 0), (0, 0))          # clockwise: an outer ring
HOLE = ((1, 1), (3, 1), (3, 3), (1, 3), (1, 1))           # anticlockwise: a hole
ISLAND = ((6, 0), (6, 2), (8, 2), (8, 0), (6, 0))         # a second outer ring of the same feature


def _layer():
    lake_land = VectorFeatureDTO(POLYGON, (OUTER, HOLE, ISLAND), {"name": "A"}, (0, 0, 8, 4))
    other = VectorFeatureDTO(POLYGON, (((10, 0), (10, 4), (14, 4), (14, 0), (10, 0)),), {"name": "B"},
                             (10, 0, 14, 4))
    return VectorLayerDTO("x.shp", "x", POLYGON, "EPSG:4326", 2, (), (lake_land, other), (0, 0, 14, 4))


@pytest.fixture
def canvas():
    canvas = VectorCanvas()
    canvas.resize(700, 300)
    canvas.set_colours(QColor(200, 30, 30, 255), QColor(200, 30, 30))
    canvas.set_layer(_layer())
    canvas.show()
    canvas.grab()                     # the first picture
    yield canvas
    canvas.deleteLater()


def _colour_at(canvas, lon, lat):
    image = canvas.grab().toImage()
    point = canvas._to_screen(lon, lat)
    return image.pixelColor(round(point.x()), round(point.y()))


def test_dragging_moves_the_picture_without_repainting_shapes(canvas, monkeypatch):
    painted = []
    original = vector_canvas._draw_feature
    monkeypatch.setattr(vector_canvas, "_draw_feature", lambda *a: (painted.append(1), original(*a)))
    canvas._dragging = True
    start = QPointF(canvas._pan)
    for step in range(1, 15):
        canvas._pan = start + QPointF(-step * 6, step * 2)   # (stays on screen)
        canvas.grab()
    # every frame used to repaint every shape (100-300 ms on admin boundaries)
    assert painted == []
    assert _colour_at(canvas, 13, 2).red() > 150        # and it is the map, moved


def test_zooming_stretches_the_picture_then_paints_it_sharp_in_the_background(canvas):
    before = canvas._picture
    canvas.wheelEvent(_Wheel(QPointF(350, 150), up=True))
    assert canvas._picture is before                     # the zoom frame only stretched it
    assert canvas._render_timer.isActive()
    for _ in range(200):                                 # the worker paints the sharp one
        QTest.qWait(10)
        if canvas._picture is not before and not canvas._rendering:
            break
    assert canvas._picture is not before
    assert canvas._picture_fits()


def test_holes_stay_holes_and_islands_are_filled(canvas):
    assert _colour_at(canvas, 0.5, 0.5).green() < 100    # the land, filled red
    assert _colour_at(canvas, 2, 2).green() > 150        # the lake (a hole): the background shows
    assert _colour_at(canvas, 7, 1).green() < 100        # the island, filled
    cached = vector_canvas._cache_feature(canvas._geo[0], POLYGON, *canvas._transform(canvas._pan))
    assert len(cached.paths) == 2                        # outer + its hole, then the island


def test_the_feature_under_the_pointer_is_found_after_zooming_and_panning(canvas):
    canvas._zoom = 3.0
    canvas._pan = QPointF(40, -10)
    assert canvas._feature_at(canvas._to_screen(0.5, 0.5)) == 0
    assert canvas._feature_at(canvas._to_screen(7, 1)) == 0      # its island
    assert canvas._feature_at(canvas._to_screen(2, 2)) == -1     # inside the hole: nothing
    assert canvas._feature_at(canvas._to_screen(12, 2)) == 1


def test_a_shape_that_cannot_be_read_is_skipped_not_the_whole_file():
    import shapefile

    from backend.business.vector import vector_service

    class Reader:  # pyshp stops iterating at the bad shape (#1)
        def __len__(self):
            return 3

        def iterShapeRecords(self):  # noqa: N802 (pyshp API)
            yield type("SR", (), {"shape": "s0", "record": "r0"})()
            raise shapefile.ShapefileException("Polygon requires non-empty points")

        def shape(self, i):
            if i == 1:
                raise shapefile.ShapefileException("bad")
            return f"s{i}"

        def record(self, i):
            return f"r{i}"

    assert list(vector_service._shape_records(Reader())) == [("s0", "r0"), ("s2", "r2")]


class _Wheel:
    def __init__(self, position, up):
        self._position, self._up = position, up

    def position(self):
        return self._position

    def angleDelta(self):  # noqa: N802 (Qt API)
        from PyQt6.QtCore import QPoint

        return QPoint(0, 120 if self._up else -120)

    def accept(self):
        pass
