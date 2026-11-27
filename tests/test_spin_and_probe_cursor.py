"""Number boxes show their up / down arrows on every page and theme, and the map's
value-reading pointer is a hollow ring in the theme's least-used colour."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend import palette, theme, theming  # noqa: E402

app = QApplication.instance() or QApplication([])


@pytest.fixture
def each_theme():
    start = palette.THEME
    yield list(palette.PALETTES)
    theming.set_theme(start, persist=False)


# ------------------------------------------------------------------ number box arrows
def test_the_app_stylesheet_draws_number_box_arrows_in_the_theme_ink(each_theme):
    for name in each_theme:
        theming.set_theme(name, persist=False)
        sheet = theme.STYLESHEET
        # in the app-wide sheet, so pages that restyle their boxes (Data catalog, IDW, DEM,
        # Analysis...) still get them: they used to show two blank buttons
        assert "QSpinBox::up-arrow" in sheet and "QDoubleSpinBox::down-arrow" in sheet
        up = Path(theme.chevron_icon("up", theme.INK))
        assert f'url("{up.as_posix()}")' in sheet
        assert up.exists() and theme.INK.lower() in up.read_text(encoding="utf-8").lower()


def test_the_parameter_form_arrows_follow_the_theme_too(each_theme):
    from frontend import form_theme

    theming.set_theme("navy", persist=False)
    assert theme.chevron_icon("up", form_theme.INK) in form_theme.FORM_STYLESHEET
    assert theme.chevron_icon("down", form_theme.INK) in form_theme.FORM_STYLESHEET


# ------------------------------------------------------------------ the probe cursor
def test_the_least_used_colour_is_measured_and_is_each_themes_second_colour(each_theme):
    for name in each_theme:
        theming.set_theme(name, persist=False)
        assert theme.least_used_colour() == palette.ACTIVE["OCEAN"], name


def test_the_ring_is_hollow_and_drawn_in_that_colour(each_theme):
    from frontend.widgets.probe_cursor import RADIUS, SIZE, probe_pixmap

    for name in ("light", "indigo", "bone"):
        theming.set_theme(name, persist=False)
        image = probe_pixmap().toImage()
        centre = SIZE // 2
        assert image.pixelColor(centre, centre).alpha() == 0                  # hollow
        on_ring = image.pixelColor(round(centre + RADIUS), centre)
        want = QColor(theme.least_used_colour())
        assert max(abs(on_ring.red() - want.red()), abs(on_ring.green() - want.green()),
                   abs(on_ring.blue() - want.blue())) < 40, name


def test_the_map_shows_the_ring_over_the_picture_and_the_hand_elsewhere(each_theme):
    import numpy as np

    from frontend.widgets.map_area import MapArea
    from frontend.widgets.raster_canvas import rgba_to_image

    theming.set_theme("light", persist=False)
    area = MapArea()
    area.set_image(rgba_to_image(np.full((4, 6, 4), 255, "uint8")), (73, 31, 74, 32), 6)
    viewport = area.canvas.viewport()
    area.canvas._show_cursor(True)
    assert viewport.cursor().shape() != Qt.CursorShape.BitmapCursor     # no values to read: no ring

    area.set_value_probe(lambda x, y: ("1", "x"))
    area.canvas._show_cursor(True)
    assert viewport.cursor().shape() == Qt.CursorShape.BitmapCursor
    first = viewport.cursor().pixmap().toImage()
    area.canvas._show_cursor(False)
    assert viewport.cursor().shape() == Qt.CursorShape.OpenHandCursor   # off the picture: drag hand

    theming.set_theme("navy", persist=False)                             # the ring follows the theme
    area.canvas._show_cursor(True)
    assert viewport.cursor().pixmap().toImage() != first
    area.deleteLater()
