"""The Vector Maps page, on a real (small) shapefile (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
pytest.importorskip("shapefile")
from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import BusinessFacade  # noqa: E402
from backend.business.vector import VectorService  # noqa: E402
from frontend.views import vector_map_view as view_module  # noqa: E402
from frontend.views.vector_map_view import VectorMapView  # noqa: E402
from tests.test_vector_service import write_polygons  # noqa: E402


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
    monkeypatch.setattr(view_module, "run_task", _run_now)
    facade = BusinessFacade(MagicMock(), MagicMock(), MagicMock(), MagicMock(), vector_service=VectorService())
    view = VectorMapView(facade)
    view.resize(1100, 700)
    yield view
    view.deleteLater()


def test_opens_a_shapefile_and_fills_the_panel_and_table(page, tmp_path):
    page.load(str(write_polygons(tmp_path / "areas.shp")))

    assert page._layer is not None and page._layer.feature_count == 2
    assert page.detail_labels["kind"].text() == "Polygons"
    assert page.detail_labels["features"].text() == "2"
    assert page.detail_labels["crs"].text() == "EPSG:4326"
    # Attribute table mirrors the fields and rows.
    assert page.table.columnCount() == 2
    assert page.table.rowCount() == 2
    assert [page.table.horizontalHeaderItem(c).text() for c in range(2)] == ["name", "pop"]
    assert page.table.item(0, 0).text() == "Alpha"
    assert page.fit_button.isEnabled() and page.zoom_button.isEnabled()


def test_selecting_a_row_selects_the_feature_on_the_canvas(page, tmp_path):
    page.load(str(write_polygons(tmp_path / "areas.shp")))
    page.table.selectRow(1)
    assert page.canvas.selected() == 1
    assert "Feature 2 of 2" in page.identify_label.text()


def test_clicking_the_canvas_selects_the_row_and_identifies(page, tmp_path):
    page.load(str(write_polygons(tmp_path / "areas.shp")))
    page.canvas.fit()
    # The first polygon spans lon 0..2, lat 0..2; aim the pointer at its centre on screen.
    centre = page.canvas._to_screen(1.0, 1.0)
    assert page.canvas._feature_at(centre) == 0
    page.canvas._selected = -1
    page.canvas.feature_clicked.emit(page.canvas._feature_at(centre))
    assert page.table.selectionModel().selectedRows()[0].row() == 0


def test_bad_file_shows_an_error_and_clears(page, tmp_path):
    bad = tmp_path / "broken.shp"
    bad.write_bytes(b"not a shapefile")
    page.load(str(bad))
    assert page._layer is None
    assert page.table.rowCount() == 0
    assert not page.fit_button.isEnabled()
