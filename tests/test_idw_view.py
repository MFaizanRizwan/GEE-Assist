"""The IDW Interpolation page, on a small point shapefile (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
shapefile = pytest.importorskip("shapefile")
pytest.importorskip("rasterio")
from PyQt6.QtWidgets import QApplication  # noqa: E402

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
