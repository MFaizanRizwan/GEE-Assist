"""The Prediction (ML) page, driven with the real prediction service on small synthetic files."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PyQt6")
pytest.importorskip("sklearn")
from PyQt6.QtCore import QDate, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

# The application first, as in the other UI tests: the page imports the web map, and with Qt
# WebEngine set up before the application the home window builds a live web view, which cannot
# run in a headless test.
app = QApplication.instance() or QApplication([])

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.business.prediction import PredictionService  # noqa: E402
from backend.dto.prediction_dto import CHANGE, CLASSIFY, FORECAST  # noqa: E402
from frontend.views import prediction_view as view_module  # noqa: E402
from frontend.views.prediction_view import PredictionView  # noqa: E402
from tests.test_prediction_service import DATES, SIZE, _write  # noqa: E402


def _run_now(owner, fn, *args, on_success=None, on_error=None):
    try:
        result = fn(*args)
    except Exception as exc:  # noqa: BLE001
        if on_error:
            on_error(exc)
    else:
        if on_success:
            on_success(result)


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(view_module, "run_task", _run_now)
    service = PredictionService()
    facade = MagicMock(spec=IBusinessFacade)
    facade.prediction_algorithms.side_effect = service.algorithms
    facade.describe_prediction_input.side_effect = service.describe
    facade.run_prediction.side_effect = service.run
    facade.save_prediction.side_effect = service.save
    facade.list_analysis_datasets.return_value = []
    facade.list_saved_results.return_value = []
    view = PredictionView(facade)
    view.resize(1400, 900)
    view.show()
    yield view, facade
    view.deleteLater()


def _ndvi_files(tmp_path):
    rng = np.random.default_rng(2)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    paths = []
    for year, day in enumerate(DATES):
        values = 0.3 + 0.2 * yy / SIZE + 0.04 * year + rng.normal(0, 0.005, (SIZE, SIZE))
        folder = tmp_path / f"Sentinel-2_73.0000_31.0000_{day}_{day}"
        folder.mkdir()
        paths.append(_write(folder / "ndvi.tif", [values], ["NDVI"]))
    return paths


def test_the_page_offers_the_four_tasks_and_recommended_algorithms(page):
    view, _ = page
    assert set(view.task_tiles) == {"forecast", "change", "classify", "anomaly"}
    assert view.task == FORECAST and view.task_tiles[FORECAST].isChecked()
    chosen = view.chosen_algorithms()
    assert {"persistence", "trend", "random_forest", "xgboost"} <= set(chosen)
    view.select_algorithms("all")
    assert len(view.chosen_algorithms()) >= 20
    view.select_algorithms("none")
    assert view.chosen_algorithms() == [] and not view.run_button.isEnabled()
    view.choose_task(CLASSIFY)
    assert view.labels_button.isVisibleTo(view) and not view.band_box.isVisibleTo(view)
    assert "torch_lstm" not in {a.key for a in view.algorithms}


def test_files_are_dated_from_their_names_and_the_latest_is_the_present(page, tmp_path):
    view, _ = page
    paths = _ndvi_files(tmp_path)
    view.add_inputs([(p, "") for p in reversed(paths)])
    table = view.input_table
    assert [table.item(r, 0).text() for r in range(table.rowCount())] == DATES
    assert table.item(table.rowCount() - 1, 2).text() == "present"
    assert view.band_box.currentText() == "NDVI"
    assert view.target_date.date() > QDate(2024, 6, 1)          # one usual step after the present
    table.item(0, 0).setText("2019-06-01")                       # the user corrects a date
    assert view._ordered_inputs()[0].date == "2019-06-01"


def test_a_forecast_run_fills_the_leaderboard_and_the_map(page, tmp_path):
    view, facade = page
    view.add_inputs([(p, "") for p in _ndvi_files(tmp_path)])
    view.select_algorithms("none")
    for item in view._algorithm_items():
        if item.data(0, Qt.ItemDataRole.UserRole) in ("persistence", "trend", "linear", "random_forest"):
            item.setCheckState(0, Qt.CheckState.Checked)
    view.working_size.setValue(64)
    view.sample_size.setValue(2000)
    assert view.run_button.isEnabled() and "4 algorithms" in view.run_button.text()
    view.run_button.click()
    result = view.result
    assert result is not None and result.task == FORECAST
    board = view.leaderboard
    headers = [board.horizontalHeaderItem(c).text() for c in range(board.columnCount())]
    assert headers[:3] == ["#", "Algorithm", "RMSE"] and "R²" in headers
    assert board.rowCount() == len(result.scores) and board.item(0, 0).text() == "1"
    assert view.map_area.canvas.has_image()
    assert view.layer_box.count() >= 3                                 # forecast, uncertainty, change, present
    # another model's map
    other = next(s for s in result.scores if s.key == "persistence")
    view.show_model(other.key)
    assert other.label in view.result_title.text()
    # the value under the pointer, and the change layer
    assert view._value_at(5, 5)[0] not in ("", None)
    view.layer_box.setCurrentIndex(view.layer_box.findData("difference"))
    assert view.map_area.legend.isVisible()
    path = tmp_path / "saved.tif"
    monkey_save = view_module.QFileDialog.getSaveFileName
    view_module.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(path), ""))
    try:
        view.save()
    finally:
        view_module.QFileDialog.getSaveFileName = monkey_save
    assert path.exists() and "Saved to" in view.banner.text()


def test_future_land_cover_shows_classes_with_names(page, tmp_path):
    view, _ = page
    view.choose_task(CHANGE)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    distance = np.hypot(yy - SIZE / 2, xx - SIZE / 2)
    files = [(_write(tmp_path / f"lc_{d}.tif", [np.where(distance < 5 + 3 * i, 6, 4)], ["label"], "uint8", 255), d)
             for i, d in enumerate(DATES)]
    view.add_inputs(files)
    assert view.band_box.currentText() == "label"
    view.select_algorithms("none")
    for item in view._algorithm_items():
        if item.data(0, Qt.ItemDataRole.UserRole) in ("no_change", "random_forest"):
            item.setCheckState(0, Qt.CheckState.Checked)
    view.working_size.setValue(64)
    view.run()
    assert view.result is not None and view.result.task == CHANGE
    texts = [label.text() for label in view.map_area.legend.findChildren(type(view.title))]
    assert any("Built area" in t for t in texts) and any("Crops" in t for t in texts)
    assert view._value_at(20, 20)[0] == "Built area"


def test_the_side_bar_has_a_prediction_button_that_opens_the_page():
    from backend.dto.user_dto import UserDTO
    from frontend.views.home_window import HomeWindow
    from frontend.widgets.side_icons import PredictIcon
    from tests.test_analysis_ui import _facade

    user = UserDTO(id="u1", username="a", email="a@example.com", full_name="A", role="user", is_active=True,
                   email_verified=True)
    facade = _facade()
    facade.get_current_user.return_value = user
    facade.prediction_algorithms.side_effect = PredictionService().algorithms
    home = HomeWindow(facade, user)
    try:
        assert isinstance(home.prediction_button.icon_drawing, PredictIcon)
        home.prediction_button.click()
        assert home.current_page() is home.prediction
        home.show_dashboard()
        home.menu_bar.view_prediction.trigger()
        assert home.current_page() is home.prediction
        assert home.menu_bar.view_prediction.shortcut().toString() == "Ctrl+Shift+P"
    finally:
        home.terminal.shutdown()
        home.deleteLater()
        QTest.qWait(10)


def test_the_icon_animates_its_forecast():
    from frontend.widgets.side_icons import PredictIcon

    assert PredictIcon.forecast_reach(None) == 1.0
    assert PredictIcon.forecast_reach(0.0) < PredictIcon.forecast_reach(0.5) <= 1.0


def test_the_page_shows_where_it_trains_and_can_turn_the_gpu_off(page):
    from backend.dto.analysis_dto import GPU_DEDICATED, GpuDTO
    from backend.dto.prediction_dto import PredictionDeviceDTO

    view, _facade = page
    rtx = GpuDTO("NVIDIA GeForce RTX 3060", "NVIDIA", GPU_DEDICATED)
    view._on_device(PredictionDeviceDTO("NVIDIA GeForce RTX 3060", ("xgboost",), (rtx,), "XGBoost models train "
                                                                                       "on the RTX 3060."))
    assert view.use_gpu.isVisibleTo(view) and view.use_gpu.isChecked() and view.use_gpu.isEnabled()
    assert "GPU: NVIDIA GeForce RTX 3060" in view.device_label.text()
    assert view.request().options.use_gpu is True
    view.use_gpu.setChecked(False)
    assert view.device_label.text() == "Trains on the CPU" and "turned off" in view.device_label.toolTip()
    assert view.request().options.use_gpu is False

    view._on_device(PredictionDeviceDTO("CPU", (), (), "No NVIDIA GPU (graphics: none found)."))
    assert not view.use_gpu.isVisibleTo(view) and view.request().options.use_gpu is False
    assert view.device_label.text() == "Trains on the CPU" and "No NVIDIA GPU" in view.device_label.toolTip()
