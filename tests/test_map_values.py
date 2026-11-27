"""The analysis map: the value under the pointer, legends that say what the colours mean,
full screen, and "Show on map" laying the result over the world map with its extras."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from backend.dto.map_dto import LegendDTO, MapLayerDTO  # noqa: E402
from frontend.widgets.layer_meaning import meaning  # noqa: E402
from frontend.widgets.layer_values import layer_value, layer_value_at  # noqa: E402
from frontend.widgets.map_area import MapArea  # noqa: E402
from frontend.widgets.raster_canvas import rgba_to_image  # noqa: E402

app = QApplication.instance() or QApplication([])

BOUNDS = (73.0, 31.0, 74.0, 32.0)


def _scale_layer():
    values = np.linspace(-0.2, 0.8, 24, dtype="float32").reshape(4, 6)
    values[0, 0] = np.nan
    rgba = np.full((4, 6, 4), 200, dtype="uint8")
    return MapLayerDTO("NDVI", "NDVI", "vegetation", rgba, LegendDTO("scale", "NDVI", -0.2, 0.8, ("#000", "#fff")),
                       6, 4, BOUNDS, kind="scale", values=values)


def _class_layer():
    rgba = np.zeros((2, 2, 4), dtype="uint8")
    rgba[0, 0] = (0x39, 0x7D, 0x49, 255)   # Trees
    rgba[0, 1] = (0xDF, 0xC3, 0x5A, 255)   # Shrub
    rgba[1, 0] = (1, 2, 3, 255)            # a colour of no class
    return MapLayerDTO("LC", "Land cover", "classes", rgba, LegendDTO("classes", "Land cover", 0, 1, ()), 2, 2,
                       BOUNDS, kind="classes", class_fractions=(("Trees", "#397D49", 0.5), ("Shrub", "#dfc35a", 0.5)))


# ------------------------------------------------------------------ reading a value
def test_a_continuous_layer_reads_its_own_value():
    layer = _scale_layer()
    assert layer_value(layer, 5, 3) == ("0.800", "NDVI")
    assert layer_value(layer, 0, 0) == ("no data", "NDVI")
    assert layer_value(layer, 6, 0) is None and layer_value(None, 0, 0) is None


def test_a_class_layer_names_the_class_under_the_pointer():
    layer = _class_layer()
    assert layer_value(layer, 0, 0) == ("Trees", "Land cover")
    assert layer_value(layer, 1, 0) == ("Shrub", "Land cover")   # colours match whatever their case
    assert layer_value(layer, 0, 1) is None                      # no class drawn in that colour
    assert layer_value(layer, 1, 1) == ("no data", "Land cover")  # transparent
    assert layer_value(layer, 0, 0, rows=[("Shrub", "#dfc35a")]) is None  # Trees hidden in the legend


def test_a_value_is_read_at_a_longitude_and_latitude():
    layer = _scale_layer()
    assert layer_value_at(layer, 73.99, 31.01) == ("0.800", "NDVI")   # bottom-right pixel
    assert layer_value_at(layer, 72.5, 31.5) is None                 # off the layer


def test_legends_say_what_low_and_high_values_mean():
    assert meaning("NDVI", "vegetation") == ("Bare ground / water", "Dense, healthy vegetation")
    assert meaning("NDWI", "water") == ("Land", "Open water")        # the index wins over its style
    assert meaning("NDWI (water)") == ("Land", "Open water")            # its first word is tried too
    assert meaning("dNBR", "burn")[1] == "Severely burned"
    assert meaning("PC1", "grey") is None


# ------------------------------------------------------------------ on the map
@pytest.fixture
def area():
    area = MapArea(dark=True)
    area.resize(600, 400)
    layer = _scale_layer()
    area.set_image(rgba_to_image(layer.data), layer.bounds, layer.width, keep_view=False)
    area.set_value_probe(lambda x, y: layer_value(layer, x, y))
    area.show_legend_scale("NDVI", ("#000000", "#FFFFFF"), -0.2, 0.8, meaning("NDVI", "vegetation"))
    area.show()
    QTest.qWait(30)
    yield area
    area.deleteLater()


def test_pointing_at_the_map_shows_the_value_and_place_there(area):
    canvas = area.canvas
    canvas.report_position(QPointF(5.5, 3.5))   # the pointer over the bottom-right pixel
    assert area.readout.isVisible()
    text = area.readout.text()
    assert "0.800" in text and "NDVI" in text
    assert "31.12500° N" in text and "73.91667° E" in text
    canvas.left_image.emit()
    assert not area.readout.isVisible()


def test_the_legend_says_what_its_colours_mean(area):
    texts = " ".join(label.text() for label in area.legend.findChildren(QLabel))
    assert "Dense, healthy vegetation" in texts and "Bare ground / water" in texts


def test_the_full_screen_button_shows_the_same_map_full_screen(area):
    assert area.full_button.toolTip() == "Show the map full screen"
    assert area.fit_button is not area.full_button
    area.set_opacity(0.4)
    area.full_button.click()
    window = area.full_window
    assert window is not None and window.isFullScreen()
    [copy] = window.findChildren(MapArea)
    assert copy.canvas.has_image() and copy.canvas.image_size() == area.canvas.image_size()
    assert copy.canvas.opacity() == pytest.approx(0.4)
    assert copy.legend.isVisible()
    assert copy.full_button.toolTip() == "Exit full screen (Esc)"
    copy.canvas.report_position(QPointF(5.5, 3.5))
    assert "0.800" in copy.readout.text()                       # values on the full-screen map too
    QTest.keyClick(window, Qt.Key.Key_Escape)
    QTest.qWait(20)
    assert area.full_window is None


def test_the_corner_button_of_the_full_screen_map_closes_it(area):
    window = area.open_full_screen()
    [copy] = window.findChildren(MapArea)
    copy.full_button.click()
    QTest.qWait(20)
    assert area.full_window is None


def test_an_empty_map_does_not_go_full_screen():
    empty = MapArea()
    assert empty.open_full_screen() is None
    empty.deleteLater()


# ------------------------------------------------------------------ the Analysis page
def test_show_on_map_sends_the_result_in_its_colours_with_legend_and_values(monkeypatch):
    from tests.test_analysis_ui import _facade, _wait
    from frontend.views.analysis_view import AnalysisView
    from PyQt6.QtGui import QImage

    facade = _facade()
    facade.get_map_layers.return_value = [_scale_layer()]
    view = AnalysisView(facade)
    view.resize(1300, 820)
    view.show()
    _wait(lambda: view.options and view.device is not None)
    view.run()
    _wait(lambda: view.layers)
    sent = []
    view.show_on_map_requested.connect(lambda *args: sent.append(args))
    view.map_button.click()

    [(png, bounds, title, extras)] = sent
    assert bounds == BOUNDS and title.endswith("NDVI")
    image = QImage.fromData(png, "PNG")
    expected = view.sym_panel.current_rgba()[3, 5]           # the symbology's colours, not the raw drawing
    assert image.pixelColor(5, 3).getRgb()[:3] == tuple(int(c) for c in expected[:3])
    assert extras.legend[0] == "scale" and extras.legend[1][4] == meaning("NDVI", "vegetation")
    assert extras.probe(73.99, 31.01) == ("0.800", "NDVI")
    # and the page's own map shows the value under the pointer
    view.canvas.report_position(QPointF(5.5, 3.5))
    assert "0.800" in view.map_area.readout.text()
    view.deleteLater()


# ------------------------------------------------------------------ the full-screen world map
def test_the_world_map_window_sets_opacity_shows_the_legend_and_values(monkeypatch):
    from PyQt6.QtCore import pyqtSignal
    from PyQt6.QtWidgets import QWidget

    from frontend.views import full_map_window

    class FakeWebMap(QWidget):  # the real one is a web page
        pointer_moved = pyqtSignal(float, float)
        pointer_left = pyqtSignal()

        def __init__(self):
            super().__init__()
            self.sent = []

        def show_image(self, png, bounds, title, opacity=0.8, controls=True):
            self.sent.append(("image", png, bounds, title, opacity, controls))

        def set_image_opacity(self, opacity):
            self.sent.append(("opacity", opacity))

    monkeypatch.setattr(full_map_window, "AoiMapWidget", FakeWebMap)
    monkeypatch.setattr(full_map_window, "PROBE_DELAY_MS", 0)
    layer = _scale_layer()
    extras = full_map_window.MapExtras(
        ("scale", ("NDVI", ("#000000", "#FFFFFF"), -0.2, 0.8, meaning("NDVI", "vegetation"))),
        lambda lon, lat: layer_value_at(layer, lon, lat))
    window = full_map_window.FullMapWindow(b"png", BOUNDS, "Place · NDVI", extras)
    window.resize(1200, 800)
    window.show()
    QTest.qWait(20)

    # the picture goes on without the map's own box: the window's bar has the opacity
    assert window.map.sent[0] == ("image", b"png", BOUNDS, "Place · NDVI", 0.8, False)
    window.opacity.setValue(35)
    assert window.map.sent[-1] == ("opacity", 0.35) and window.opacity_value.text() == "35%"
    assert window.legend.isVisible()
    assert "Dense, healthy vegetation" in " ".join(l.text() for l in window.legend.findChildren(QLabel))

    window.map.pointer_moved.emit(73.99, 31.01)
    QTest.qWait(20)
    assert window.readout.isVisible() and "0.800" in window.readout.text()
    window.map.pointer_left.emit()
    assert not window.readout.isVisible()

    closed = []
    window.destroyed.connect(lambda *_: closed.append(True))
    QTest.keyClick(window, Qt.Key.Key_Escape)
    QTest.qWait(20)
    assert closed
