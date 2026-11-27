"""The rotating-Earth loader: a natively painted globe that turns while it is on screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.widgets import earth_loader  # noqa: E402
from frontend.widgets.earth_loader import EarthLoader, GlobeWidget, land_rings, project  # noqa: E402

app = QApplication.instance() or QApplication([])


def _frame(globe: GlobeWidget, ms: float) -> QImage:
    image = QImage(globe.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    globe.paint_frame(ms, painter)
    painter.end()
    return image


def test_the_land_outline_becomes_longitude_latitude_rings():
    assert land_rings("M0 0 100 0 100 50Z") == [[-180.0, 90.0, 0.0, 90.0, 0.0, 0.0]]


def test_the_projection_keeps_the_land_on_the_disc_and_turns_it():
    for lon0 in (0, 90, 200):
        rings = project(lon0)
        assert rings and all((ring[:, 0] ** 2 + ring[:, 1] ** 2 <= 1.0 + 1e-9).all() for ring in rings)
    assert [r.shape for r in project(0)] != [r.shape for r in project(120)]  # other continents face us


def test_the_globe_is_drawn_round_and_changes_from_frame_to_frame():
    globe = GlobeWidget(120)
    first, later = _frame(globe, 0), _frame(globe, 1500)
    cx, cy = globe.width() // 2, globe.height() // 2
    assert first.pixelColor(cx, cy) != first.pixelColor(2, 2)            # the globe is there ...
    corner = (cx - int(120 * 0.46 * 0.9), cy - int(120 * 0.46 * 0.9))     # ... and round: no square corner
    assert first.pixelColor(*corner).name() == "#ffffff"
    assert first != later                                                 # it turns


def test_it_animates_only_while_on_screen_and_updates_its_caption():
    loader = EarthLoader("Running analysis…", "Starting…", size=120)
    loader.resize(840, 480)
    loader.show()
    QTest.qWait(50)
    assert loader.globe.is_animating()
    loader.set_text("Running analysis on the CPU…", "50% complete")
    assert loader.label.text() == "Running analysis on the CPU…" and loader.detail.text() == "50% complete"
    loader.set_text("Explaining…")
    assert loader.detail.isHidden()
    loader.hide()
    assert not loader.globe.is_animating()
    loader.deleteLater()


def test_the_loader_no_longer_needs_a_web_engine():
    assert not hasattr(earth_loader, "_web_engine_view_class")
