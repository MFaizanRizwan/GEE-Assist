"""The Analysis page, the analysis table, the side bar's Analysis button and the View menu (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.data.dao.formula_dao import FormulaDAO  # noqa: E402
from backend.dto.analysis_dto import (  # noqa: E402
    GPU_INTEGRATED,
    AnalysisOptionDTO,
    AnalysisRequestDTO,
    ComputeDeviceDTO,
    GpuDTO,
    ProcessOptionDTO,
)
from backend.dto.download_dto import DatasetDTO  # noqa: E402
from backend.dto.map_dto import LegendDTO, MapLayerDTO  # noqa: E402
from backend.dto.result_dto import ResultDTO, ResultLayerDTO  # noqa: E402
from backend.dto.user_dto import UserDTO  # noqa: E402
from frontend.widgets.side_icons import AnalysisIcon  # noqa: E402

app = QApplication.instance() or QApplication([])

DAO = FormulaDAO()
AFTER = DatasetDTO("1", "COPERNICUS/S2_SR_HARMONIZED", "C:/data/after.tif", name="Sentinel-2_1_2_2024-06-01_2024-06-30",
                   satellite="Sentinel-2", start_date="2024-06-01", end_date="2024-06-30", size_bytes=2048)
BEFORE = DatasetDTO("2", "COPERNICUS/S2_SR_HARMONIZED", "C:/data/before.tif", name="Sentinel-2_1_2_2023-06-01_2023-06-30",
                    satellite="Sentinel-2", start_date="2023-06-01", end_date="2023-06-30")
OPTIONS = [
    AnalysisOptionDTO("Vegetation", "Greenness", (
        ProcessOptionDTO("NDVI", "Normalized Difference Vegetation Index", True),
        ProcessOptionDTO("SAVI", "Soil Adjusted Vegetation Index", True, params=("savi_l",)),
        ProcessOptionDTO("NDRE", "Normalized Difference Red Edge", False, "Needs the red-edge 1 band."),
    )),
    AnalysisOptionDTO("Burn", "Fire", (ProcessOptionDTO("dNBR", "Differenced NBR", True, periods=2),)),
    AnalysisOptionDTO("Thermal", "Heat", (ProcessOptionDTO("LSTMapping", "LST", False, "Needs a thermal band."),)),
]
CPU = ComputeDeviceDTO("numpy", "CPU", (GpuDTO("AMD Radeon (TM) Graphics", "AMD", GPU_INTEGRATED),),
                       "No dedicated GPU (graphics: AMD Radeon (TM) Graphics), so analyses run on the CPU.")


def _wait(condition, timeout_ms=3000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    assert condition()


def _facade():
    facade = MagicMock(spec=IBusinessFacade)
    facade.list_formulas.return_value = DAO.find_all()
    facade.formula_categories.return_value = DAO.categories()
    facade.list_analysis_datasets.return_value = [AFTER, BEFORE]
    facade.get_available_analyses.return_value = OPTIONS
    facade.get_compute_device.return_value = CPU
    facade.list_downloads.return_value = []
    facade.get_chunk_size_mb.return_value = 500
    layer = MapLayerDTO("NDVI", "NDVI", "vegetation", __import__("numpy").zeros((4, 6, 4), dtype="uint8"),
                        LegendDTO("scale", "NDVI", -0.2, 0.8, ("#000000", "#FFFFFF")), 6, 4, (73, 31, 74, 32))
    facade.get_map_layers.return_value = [layer]
    facade.run_analysis.return_value = ResultDTO(
        "r1", "Vegetation", ["NDVI"], {"NDVI mean": 0.42}, "C:/out/result.tif", dataset=AFTER,
        layers=[ResultLayerDTO("NDVI", "NDVI", "vegetation")], device="CPU", seconds=0.5)
    return facade


# ------------------------------------------------------------------ the icon
def test_analysis_icon_animates_its_bars_and_lens():
    assert AnalysisIcon.lens_x(None) == pytest.approx(0.7)
    assert AnalysisIcon.lens_x(0.0) < AnalysisIcon.lens_x(0.5)          # sweeps across ...
    assert AnalysisIcon.lens_x(1.0) == pytest.approx(AnalysisIcon.lens_x(0.0))  # ... and back
    heights = [AnalysisIcon.bar_height(t, 0) for t in (0.0, 0.25, 0.5, 0.75)]
    assert max(heights) - min(heights) > 0.5 and all(0.0 < h <= 1.0 for h in heights)
    assert AnalysisIcon.bar_height(0.25, 0) != AnalysisIcon.bar_height(0.25, 1)  # a wave, not in step
    image = QImage(40, 40, QImage.Format.Format_ARGB32)
    for t in (None, 0.3):
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        AnalysisIcon().paint(painter, QRectF(4, 4, 32, 32), t)
        painter.end()
        assert image.pixelColor(20, 20) != image.pixelColor(0, 0) or image.pixelColor(10, 33) != \
            image.pixelColor(0, 0)


# ------------------------------------------------------------------ the analysis table
@pytest.fixture
def table():
    from frontend.views.analysis_table_view import AnalysisTableView

    view = AnalysisTableView(_facade())
    view.resize(1300, 800)
    view.load()
    yield view
    view.deleteLater()


def test_table_lists_every_formula_grouped_by_category(table):
    assert len(table.visible_formulas()) == len(DAO.find_all())
    group_rows = table.table.rowCount() - len(table.visible_formulas())
    assert group_rows == len(DAO.categories())
    assert table.formula_at(1).key == "NDVI"  # row 0 is the "VEGETATION" group row


def test_table_filters_by_category_and_search(table):
    table.set_category("Water")
    assert {f.category for f in table.visible_formulas()} == {"Water"}
    assert "MNDWI" in [f.key for f in table.visible_formulas()]
    table.set_category("All")
    table.search.setText("chlorophyll")
    keys = [f.key for f in table.visible_formulas()]
    assert "NDCI" in keys and "GCI" in keys and "NDVI" not in keys
    table.search.setText("cigreen")  # aliases are searched too
    assert [f.key for f in table.visible_formulas()] == ["GCI"]
    assert table.detail.key.text() == "GCI"  # a single match is shown in full


def test_selecting_a_row_shows_it_in_full(table):
    assert table.select_formula("dNBR")
    assert table.detail.key.text() == "dNBR"
    assert "NBRpre − NBRpost" in table.detail.formula.text()
    assert "before and after" in table.detail.bands.text()
    assert table.select_formula("SPI")
    assert "Reference only" in table.detail.status.text() and table.detail.note.isVisibleTo(table.detail)


# ------------------------------------------------------------------ the analysis page
@pytest.fixture
def page():
    from frontend.views.analysis_view import AnalysisView

    facade = _facade()
    view = AnalysisView(facade)
    view.resize(1300, 820)
    view.show()
    _wait(lambda: view.options and view.device is not None)
    yield view, facade
    view.deleteLater()


def test_page_lists_datasets_and_what_they_can_run(page):
    view, facade = page
    assert view.dataset_list.count() == 2 and view.dataset is AFTER
    facade.get_available_analyses.assert_called_with(AFTER)
    assert view.category_buttons["Vegetation"].isEnabled() and not view.category_buttons["Thermal"].isEnabled()
    assert view.category == "Vegetation" and view.chosen_processes() == ["NDVI"]
    assert not view.process_boxes["NDRE"].isEnabled()
    assert "red-edge 1" in view.process_boxes["NDRE"].toolTip()
    assert view.device_label.text() == "Runs on the CPU"
    assert "AMD Radeon" in view.device_label.toolTip()
    assert not view.use_gpu.isEnabled()


def test_parameters_appear_for_the_processes_that_read_them(page):
    view, _ = page
    assert view.param_boxes == {}
    view.process_boxes["SAVI"].setChecked(True)
    assert list(view.param_boxes) == ["savi_l"] and view.param_boxes["savi_l"].value() == pytest.approx(0.5)
    view.param_boxes["savi_l"].setValue(0.25)
    request = view.build_request()
    assert request == AnalysisRequestDTO("Vegetation", ["NDVI", "SAVI"], {"savi_l": 0.25}, [], use_gpu=False)


def test_before_after_processes_ask_for_an_earlier_dataset(page):
    view, facade = page
    view.choose_category("Burn")
    assert view.chosen_processes() == ["dNBR"] and view.compare_list.isVisibleTo(view)
    view.run()
    assert "Compare with" in view.banner.text() and not facade.run_analysis.called
    view.set_compare([BEFORE.path])
    assert view.compare_datasets() == [BEFORE]
    view.run()
    _wait(lambda: facade.run_analysis.called)
    dataset, request = facade.run_analysis.call_args.args[:2]
    assert dataset is AFTER and request.compare_with == [BEFORE] and request.processes == ["dNBR"]


def test_running_shows_layers_and_numbers(page):
    view, facade = page
    opened = []
    view.open_in_viewer_requested.connect(opened.append)
    view.run()
    _wait(lambda: view.layers)
    assert not view.running and view.run_button.isEnabled()
    assert view.layer_box.count() == 1 and view.canvas.has_image()
    assert view.metrics_table.item(0, 0).text() == "NDVI mean" and view.metrics_table.item(0, 1).text() == "0.420"
    assert "CPU" in view.result_info.text()
    view.viewer_button.click()
    assert opened == ["C:/out/result.tif"]


def test_errors_are_shown_and_the_page_can_run_again(page):
    from backend.exceptions import AnalysisError

    view, facade = page
    facade.run_analysis.side_effect = AnalysisError("NDVI: the file is gone.")
    view.run()
    _wait(lambda: not view.running)
    assert view.banner.text() == "NDVI: the file is gone." and view.run_button.isEnabled()


# ------------------------------------------------------------------ in the signed-in window
@pytest.fixture
def window():
    from frontend.views.home_window import HomeWindow

    user = UserDTO(id="u1", username="ayesha", email="a@example.com", full_name="Ayesha Khan", role="user",
                   is_active=True, email_verified=True)
    facade = _facade()
    facade.get_current_user.return_value = user
    home = HomeWindow(facade, user)
    yield home
    home.terminal.shutdown()
    home.deleteLater()


def test_side_bar_has_an_animated_analysis_button(window):
    assert isinstance(window.analysis_button.icon_drawing, AnalysisIcon)
    window.analysis_button.click()
    assert window.current_page() is window.analysis
    assert not window.analysis_button.isVisibleTo(window)  # like the other pages' buttons
    window.show_dashboard()
    assert window.analysis_button.isVisibleTo(window)


def test_analysis_table_opens_from_the_view_menu_only(window):
    window.menu_bar.view_analysis_table.trigger()
    assert window.current_page() is window.analysis_table
    names = [button.full_text for button in window.side_bar.findChildren(type(window.analysis_button))]
    assert not any("table" in name.lower() for name in names)
    window.menu_bar.view_analysis.trigger()
    assert window.current_page() is window.analysis
