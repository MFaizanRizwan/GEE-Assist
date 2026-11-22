"""The Digital Elevation Model page, on a small synthetic DEM (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
pytest.importorskip("rasterio")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import BusinessFacade  # noqa: E402
from backend.business.terrain import TerrainService  # noqa: E402
from frontend.views import dem_view as dem_module  # noqa: E402
from frontend.views.dem_view import DemView  # noqa: E402
from tests.test_terrain_service import east_ramp, write_dem  # noqa: E402


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
    monkeypatch.setattr(dem_module, "run_task", _run_now)
    facade = BusinessFacade(MagicMock(), MagicMock(), MagicMock(), MagicMock(), terrain_service=TerrainService())
    view = DemView(facade)
    view.resize(1100, 700)
    yield view
    view.deleteLater()


def test_opens_a_dem_and_shows_elevation(page, tmp_path):
    page.load(str(write_dem(tmp_path / "dem.tif", east_ramp())))
    assert page.info is not None
    assert page.product is not None and page.product.key == "elevation"
    assert page.canvas.has_image()
    assert page.detail_labels["cell"].text() == "30 × 30 m"
    assert "0 to 390 m" in page.detail_labels["elevation"].text()


def test_switching_surface_recomputes_and_toggles_controls(page, tmp_path):
    page.load(str(write_dem(tmp_path / "dem.tif", east_ramp())))

    page.product_box.setCurrentIndex([page.product_box.itemData(i) for i in range(page.product_box.count())]
                                     .index("hillshade"))
    assert page.product.key == "hillshade"
    assert not page.azimuth.isHidden() and not page.altitude.isHidden()  # hillshade controls appear

    page.product_box.setCurrentIndex([page.product_box.itemData(i) for i in range(page.product_box.count())]
                                     .index("contours"))
    assert page.product.key == "contours"
    assert not page.interval.isHidden()
    assert not page.save_button.isEnabled()  # contours are a picture, nothing to save


def test_reads_elevation_under_the_pointer(page, tmp_path):
    page.load(str(write_dem(tmp_path / "dem.tif", east_ramp())))
    page._pointer = (20.0, 20.0)
    page._read_value()
    assert page.pointer_label.text().startswith("Elevation (shaded relief):")


def test_pointer_over_a_no_data_pixel_does_not_crash(page, tmp_path):
    import numpy as np

    page.load(str(write_dem(tmp_path / "dem.tif", east_ramp())))
    page.product.values[0, 0] = np.float32("nan")  # a no-data pixel
    page._pointer = (0.0, 0.0)
    page._read_value()  # used to raise ValueError: cannot convert float NaN to integer
    assert "no data" in page.pointer_label.text()


def test_bad_dem_shows_an_error(page, tmp_path):
    bad = tmp_path / "broken.tif"
    bad.write_bytes(b"not a geotiff")
    page.load(str(bad))
    assert page.info is None
    assert not page.fit_button.isEnabled()
