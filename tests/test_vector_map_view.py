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


def test_dense_polygon_is_decimated_in_the_cache(page, tmp_path):
    """A high-vertex admin boundary must not be drawn vertex-for-vertex (that froze the app):
    the cached screen geometry drops points that fall on the same pixel."""
    import math

    import shapefile

    path = tmp_path / "dense.shp"
    writer = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    writer.field("id", "N")
    n = 20000
    ring = [[math.cos(2 * math.pi * i / n) * 5 + 70, math.sin(2 * math.pi * i / n) * 5 + 30] for i in range(n + 1)]
    writer.poly([ring])
    writer.record(1)
    writer.close()
    path.with_suffix(".prj").write_text(
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]')

    from frontend.widgets.vector_canvas import _cache_feature

    page.load(str(path))
    page.canvas.resize(800, 600)
    scale, ox, oy = page.canvas._transform(page.canvas._pan)
    cached = _cache_feature(page.canvas._geo[0], "polygon", scale, ox, oy)
    cached_points = sum(r.shape[0] for r in cached.rings)
    assert 50 < cached_points < n / 4  # far fewer screen points than the 20,001 input vertices


def test_bad_file_shows_an_error_and_clears(page, tmp_path):
    bad = tmp_path / "broken.shp"
    bad.write_bytes(b"not a shapefile")
    page.load(str(bad))
    assert page._layer is None
    assert page.table.rowCount() == 0
    assert not page.fit_button.isEnabled()
