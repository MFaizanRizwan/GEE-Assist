"""The IDW Interpolation page, on a small point shapefile (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
shapefile = pytest.importorskip("shapefile")
pytest.importorskip("rasterio")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

# The application before the page: with Qt WebEngine set up first, the page would build a live
# web map, which cannot run headless (the page then shows its "Picture" view instead).
_app = QApplication.instance() or QApplication([])

from backend.business.facade import BusinessFacade  # noqa: E402
from backend.business.interpolation import InterpolationService  # noqa: E402
from backend.business.vector import VectorService  # noqa: E402
from frontend.views import idw_view as idw_module  # noqa: E402
from frontend.views.idw_view import IdwView  # noqa: E402


def write_points(path, with_value=True):
    w = shapefile.Writer(str(path), shapeType=shapefile.POINT)
    w.field("rain", "N", decimal=2)
    w.field("name", "C")
    for (x, y, v, n) in [(0, 0, 10, "A"), (1, 0, 20, "B"), (0, 1, 30, "C"), (1, 1, 40, "D")]:
        w.point(x, y)
        w.record(v if with_value else None, n)
    w.close()
    path.with_suffix(".prj").write_text(
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]')
    return path


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _run_now(owner, fn, *args, on_success=None, on_error=None):
    try:
        result = fn(*args)
    except Exception as exc:
        if on_error:
            on_error(exc)
    else:
        if on_success:
            on_success(result)


@pytest.fixture
def page(app, monkeypatch):
    monkeypatch.setattr(idw_module, "run_task", _run_now)
    facade = BusinessFacade(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                            vector_service=VectorService(), interpolation_service=InterpolationService())
    view = IdwView(facade)
    view.resize(1100, 700)
    yield view
    view.deleteLater()


def test_loads_points_and_lists_numeric_fields(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))
    assert page._layer is not None
    assert [page.field_box.itemText(i) for i in range(page.field_box.count())] == ["rain"]  # only numeric
    assert page.detail_labels["points"].text() == "4"
    assert page.run_button.isEnabled()


def test_running_idw_produces_a_surface(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))
    page.run()
    assert page.result is not None
    assert page.canvas.has_image()
    assert page.detail_labels["field"].text() == "rain"
    assert "10" in page.detail_labels["range"].text() and "40" in page.detail_labels["range"].text()
    assert page.save_button.isEnabled()


def test_reads_an_interpolated_value_under_the_pointer(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))
    page.run()
    page._pointer = (page.result.width // 2, page.result.height // 2)
    page._read_value()
    assert page.pointer_label.text().startswith("rain:")


def test_a_polygon_layer_is_refused(page, tmp_path):
    poly = tmp_path / "areas.shp"
    w = shapefile.Writer(str(poly), shapeType=shapefile.POLYGON)
    w.field("v", "N")
    w.poly([[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]])
    w.record(1)
    w.close()
    page.load(str(poly))
    assert page._layer is None
    assert not page.run_button.isEnabled()


# ------------------------------------------------------------------ CSV points
def _csv_points(tmp_path, header="station,longitude,latitude,rain"):
    path = tmp_path / "stations.csv"
    rows = [("A", 0.0, 0.0, 10), ("B", 1.0, 0.0, 20), ("C", 0.0, 1.0, 30), ("D", 1.0, 1.0, 40)]
    path.write_text(header + "\n" + "\n".join(f"{n},{x},{y},{v}" for n, x, y, v in rows) + "\n")
    return path


def test_a_csv_of_points_is_interpolated_like_a_shapefile(page, tmp_path):
    page.load(str(_csv_points(tmp_path)))
    assert page.lon_box.isVisibleTo(page) and page.lat_box.isVisibleTo(page)
    assert (page.lon_box.currentText(), page.lat_box.currentText()) == ("longitude", "latitude")
    # the coordinates are not offered as values to interpolate
    assert [page.field_box.itemText(i) for i in range(page.field_box.count())] == ["rain"]
    assert page.run_button.isEnabled()
    page.run()
    assert page.result is not None and page.result.point_count == 4
    assert page.result.stats["min"] >= 10 and page.result.stats["max"] <= 40


def test_a_csv_with_unnamed_coordinates_waits_for_the_columns(page, tmp_path):
    page.load(str(_csv_points(tmp_path, header="name,E,N,rain")))
    assert not page.run_button.isEnabled() and "Choose the longitude and latitude" in page.banner.text()
    page.lon_box.setCurrentIndex(page.lon_box.findData("E"))
    page.lat_box.setCurrentIndex(page.lat_box.findData("N"))
    assert page.run_button.isEnabled() and page.field_box.currentText() == "rain"


def test_opening_a_shapefile_after_a_csv_hides_the_coordinate_columns(page, tmp_path):
    page.load(str(_csv_points(tmp_path)))
    page.load(str(write_points(tmp_path / "pts.shp")))
    assert not page.lon_box.isVisibleTo(page) and page.field_box.currentText() == "rain"


# ------------------------------------------------------------------ boundaries, clipping, colours, PDF
def _districts(tmp_path):
    """Two square districts side by side, each with a name (clockwise rings, as shapefiles store them)."""
    path = tmp_path / "districts.shp"
    w = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    w.field("NAME_2", "C")
    w.poly([[[-0.2, -0.2], [-0.2, 1.2], [0.5, 1.2], [0.5, -0.2], [-0.2, -0.2]]])
    w.record("West")
    w.poly([[[0.5, -0.2], [0.5, 1.2], [1.2, 1.2], [1.2, -0.2], [0.5, -0.2]]])
    w.record("East")
    w.close()
    path.with_suffix(".prj").write_text(
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]')
    return path


def test_ctrl_click_and_the_list_select_the_same_areas(page, tmp_path):
    page.load_boundaries(str(_districts(tmp_path)))
    assert page.name_box.currentText() == "NAME_2"
    assert [page.area_list.item(i).text() for i in range(page.area_list.count())] == ["West", "East"]
    page.world.feature_toggled.emit(1)                     # Ctrl+click on "East" on the map
    assert page.selected == {1} and page.area_list.item(1).checkState() == Qt.CheckState.Checked
    assert "East" in page.selection_label.text() and page.world.sent[-1] == "setSelection([1])"
    page.area_list.item(0).setCheckState(Qt.CheckState.Checked)   # ticking "West" in the list
    assert page.selected == {0, 1}
    page.world.feature_toggled.emit(1)                     # Ctrl+click again: deselected
    assert page.selected == {0}
    page.area_filter.setText("ea")
    assert page.area_list.item(0).isHidden() and not page.area_list.item(1).isHidden()


def test_a_selected_area_clips_the_surface_unless_the_toggle_is_off(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))
    page.load_boundaries(str(_districts(tmp_path)))
    page.set_selection({0})                                  # West: longitude -0.2 to 0.5
    page.run()
    clipped = page.result
    west, south, east, north = clipped.bounds
    lons = west + (np.arange(clipped.width) + 0.5) * (east - west) / clipped.width
    lats = north - (np.arange(clipped.height) + 0.5) * (north - south) / clipped.height
    assert np.isnan(clipped.values[:, lons > 0.52]).all()   # nothing outside the boundary
    assert np.isnan(clipped.values[lats > 1.22]).all()
    inside_rows = (lats > -0.15) & (lats < 1.15)
    assert np.isfinite(clipped.values[inside_rows][:, (lons > -0.15) & (lons < 0.45)]).all()
    assert "clipped to the selected boundary" in " ".join(clipped.notes)
    page.clip_toggle.setChecked(False)
    page.run()
    loose = page.result
    assert np.isfinite(loose.values).all() and loose.bounds[2] > 1.0   # spreads over the points too


def test_colours_classes_and_legends_follow_the_choices(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))
    page.run()
    assert page.classic_toggle.isChecked() and page._legend[0] == "classes"
    assert len(page._legend[1]) == 5 and page._legend[1][0][1] == "#FFFFB2"     # yellow first
    assert len(page.legend.item_texts()) >= 5 and "–" in page.legend.item_texts()[0]
    page.classes.setValue(3)
    assert len(page._legend[1]) == 3
    page.method_box.setCurrentIndex(page.method_box.findData("continuous"))
    assert page._legend[0] == "scale" and not page.classes.isEnabled()
    classic = page._rgba.copy()
    page.classic_toggle.setChecked(False)                    # Viridis
    assert not np.array_equal(classic, page._rgba)
    page.layer_toggles["boundaries"].setChecked(False)
    assert page.world.sent[-1] == 'setVisible("boundaries", false)'


def test_the_map_exports_as_a_pdf_with_its_boundaries(page, tmp_path):
    from frontend.views.map_layout_dialog import MapLayoutDialog

    page.load(str(write_points(tmp_path / "wells.shp")))
    page.load_boundaries(str(_districts(tmp_path)))
    page.set_selection({1})
    page.run()
    spec = page.layout_spec()
    assert spec.selected_rings and spec.points and spec.legend[0] == "classes"
    dialog = MapLayoutDialog(spec)
    pdf = dialog.export(str(tmp_path / "map"))
    assert pdf.endswith(".pdf") and (tmp_path / "map.pdf").read_bytes().startswith(b"%PDF")
    assert dialog.scale_item.distance()[0] > 0
    dialog.toggles["boundaries"].setChecked(False)
    assert not dialog.frame_item.show_boundaries
    dialog.deleteLater()


def test_only_the_selected_area_can_be_kept_on_the_map(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))          # points at x = 0 and x = 1
    page.load_boundaries(str(_districts(tmp_path)))
    assert not page.focus_toggles["outside_points"].isEnabled()    # nothing selected yet
    page.set_selection({0})                                        # West: x from -0.2 to 0.5
    assert page.focus_toggles["outside_points"].isEnabled()
    page.run()
    assert page.result.point_count == 4                            # IDW uses every point regardless
    assert len(page.shown_points()) == 4
    page.focus_toggles["outside_points"].setChecked(False)
    shown = page.shown_points()
    assert len(shown) == 2 and all(lon < 0.5 for lon, _lat, _f in shown)   # only the points inside West
    assert page.world.sent[-1].startswith("setPoints(") and page.world.sent[-1].count("[") == 3   # two points
    page.focus_toggles["other_areas"].setChecked(False)
    assert page.world.sent[-1] == "setOtherAreasVisible(false)"
    spec = page.layout_spec()
    assert len(spec.points) == 2 and spec.boundary_rings == spec.selected_rings   # the PDF shows the same
    page.focus_toggles["other_areas"].setChecked(True)
    assert len(page.layout_spec().boundary_rings) > len(spec.boundary_rings)


# ------------------------------------------------------------------ area names and the points' details
def _admin3(tmp_path):
    """Districts named like GADM / DIVA-GIS files: a type column that repeats, and the real names."""
    path = tmp_path / "adm3.shp"
    w = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    for name in ("NAME_1", "NAME_3", "ENGTYPE_3"):
        w.field(name, "C")
    for i, (province, district) in enumerate([("Punjab", "Lahore"), ("Punjab", "Multan"), ("Sind", "Sukkur")]):
        w.poly([[[i, 0], [i, 1], [i + 1, 1], [i + 1, 0], [i, 0]]])
        w.record(province, district, "District")
    w.close()
    return path


def test_areas_are_listed_by_their_names_with_their_region(page, tmp_path):
    page.load_boundaries(str(_admin3(tmp_path)))
    assert page.name_box.currentText() == "NAME_3"
    assert [page.area_list.item(i).text() for i in range(3)] == ["Lahore — Punjab", "Multan — Punjab", "Sukkur — Sind"]
    page.name_box.setCurrentText("ENGTYPE_3")      # a column that is "District" everywhere
    assert page.area_list.item(0).text() == "District · Lahore — Punjab"
    page.set_selection({2})
    assert "Sukkur" in page.selection_label.text()


def test_a_csv_lists_its_points_under_its_own_column_names(page, tmp_path):
    page.load(str(_csv_points(tmp_path)))
    table = page.points_table
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == ["station", "longitude", "latitude", "rain  ◆"]          # the CSV's own columns
    assert table.rowCount() == 4 and [table.item(1, c).text() for c in range(4)] == ["B", "1", "0", "20"]
    assert "SAMPLE POINTS (4)" == page.points_title.text()
    table.selectRow(2)
    assert page.world.sent[-1].startswith("fitTo(-0.01, 0.99")                  # the map goes to point C
    assert "station: C" in page.pointer_label.text()
    tooltip = page._point_tooltip(0.0, 1.0, page._layer.features[2])
    assert tooltip.startswith("<b>rain: 30</b>") and "station: C" in tooltip


def test_a_shapefile_lists_coordinates_then_its_attributes(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))
    table = page.points_table
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == ["Longitude", "Latitude", "rain  ◆", "name"]
    assert [table.item(3, c).text() for c in range(4)] == ["1.000000", "1.000000", "40", "D"]


# ------------------------------------------------------------------ the world map stays responsive
def test_the_same_points_are_not_sent_to_the_map_again(page, tmp_path):
    page.load(str(write_points(tmp_path / "wells.shp")))
    page.load_boundaries(str(_districts(tmp_path)))
    sends = sum(s.startswith("setPoints(") for s in page.world.sent)
    page.set_selection({0})                           # selecting areas does not change the points...
    page.set_selection({0, 1})
    page.set_selection(set())
    assert sum(s.startswith("setPoints(") for s in page.world.sent) == sends   # ...so none is resent
    page.set_selection({0})
    page.focus_toggles["outside_points"].setChecked(False)                     # this does
    assert sum(s.startswith("setPoints(") for s in page.world.sent) == sends + 1


def test_a_dead_map_page_is_reloaded_with_everything_on_it():
    from frontend.widgets.layer_map_widget import LayerMapWidget

    class FakePage:
        def __init__(self):
            self.ran = []

        def runJavaScript(self, script):  # noqa: N802 (Qt API)
            self.ran.append(script)

    class FakeView:
        def __init__(self):
            self._page, self.loads = FakePage(), 0

        def page(self):
            return self._page

        def load(self, _url):
            self.loads += 1

    world = LayerMapWidget()
    world._view = FakeView()
    world._ready = True
    world.set_boundaries('{"type": "FeatureCollection", "features": []}')
    world.set_selection({2})
    world.set_points([(73.0, 31.0, "pH: 6")])
    world.set_layer_visible("basemap", False)
    world.fit((73, 31, 74, 32))
    world._on_page_died()                            # Chromium's page process crashed or was killed
    assert world.reloads == 1 and world._view.loads == 1 and not world._ready
    world.set_other_areas_visible(False)             # asked while it reloads: kept for later
    world._view._page.ran.clear()
    world._on_ready()                                # the reloaded page says it is ready
    ran = world._view._page.ran
    assert [s.split("(")[0] for s in ran] == ["setBoundaries", "setSelection", "setOtherAreasVisible", "setPoints",
                                              "setVisible", "fitTo"]


def test_an_id_column_is_not_chosen_as_the_value_to_interpolate(page, tmp_path):
    path = tmp_path / "samples.csv"
    path.write_text("Sample_ID,Longitude,Latitude,pH,depth_cm\n"
                    + "".join(f"{i},{73 + i / 10},{31 + i / 20},{6 + i / 7:.2f},30\n" for i in range(1, 9)))
    page.load(str(path))
    assert page.field_box.currentText() == "pH"                        # not Sample_ID (1, 2, 3, …)
    assert [page.field_box.itemText(i) for i in range(page.field_box.count())] == ["Sample_ID", "pH", "depth_cm"]


def test_the_map_rechecks_its_size_only_once_it_is_laid_out():
    """Re-measuring the map synchronously as it reappeared (a 0 x 0 page) hung Leaflet for good."""
    from frontend.widgets.aoi_map_widget import AoiMapWidget
    from frontend.widgets.layer_map_widget import SAFE_RESIZE, LayerMapWidget

    assert "setTimeout" in SAFE_RESIZE and "clientWidth > 0" in SAFE_RESIZE and "clientHeight > 0" in SAFE_RESIZE
    world = LayerMapWidget()
    world.show()
    world.hide()
    world.show()
    assert world.sent[-1] == SAFE_RESIZE and not any(s.startswith("if (typeof map") for s in world.sent)
    html = (Path(__file__).resolve().parents[1] / "frontend" / "resources").glob("*_map.html")
    for page_file in html:
        text = page_file.read_text(encoding="utf-8")
        assert "clientWidth > 0 && el.clientHeight > 0" in text, page_file.name
    assert AoiMapWidget.showEvent.__code__.co_names.count("SAFE_RESIZE") == 1


def test_the_boundaries_can_be_drawn_as_a_one_colour_map(page):
    assert not page.fill_colour_button.isEnabled()                  # outlines: no fill controls
    page.boundary_style_box.setCurrentIndex(page.boundary_style_box.findData("filled"))
    assert page.fill_colour_button.isEnabled() and page.fill_opacity.isEnabled()
    assert page.world.sent[-1] == "setBoundaryStyle(true, \"#2E7D32\", 0.55)"
    page.set_fill_colour("#c0392b")
    page.fill_opacity.setValue(80)
    assert page.world.sent[-1] == "setBoundaryStyle(true, \"#c0392b\", 0.8)"
    page.boundary_style_box.setCurrentIndex(page.boundary_style_box.findData("outline"))
    assert page.world.sent[-1].startswith("setBoundaryStyle(false") and not page.fill_opacity.isEnabled()
