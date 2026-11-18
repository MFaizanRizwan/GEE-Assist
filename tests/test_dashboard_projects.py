"""The dashboard's project card, recent projects and recent analysis results (offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO  # noqa: E402
from frontend.views.dashboard_view import DashboardView, category_label  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dashboard(app):
    view = DashboardView()
    yield view
    view.deleteLater()


def _project(n: int) -> ProjectDTO:
    return ProjectDTO(id=f"p{n}", name=f"Project {n}", folder=f"D:/work/Project {n}")


def _record(n: int, saved=True) -> AnalysisRecordDTO:
    return AnalysisRecordDTO(id=f"r{n}", category="Vegetation", processes=["NDVI", "EVI"],
                             metrics={"NDVI mean": 0.4213}, saved=saved, created_at="2026-11-14T12:30:00")


def _click(widget) -> None:
    point = QPointF(5, 5)
    for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(widget, QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton,
                                                   Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def test_without_a_project_it_says_how_to_create_or_open_one(dashboard):
    assert dashboard.project_heading.pages.currentIndex() == 0
    assert "File → New project…" in dashboard.project_heading.empty_text.text()
    assert "File → Open project…" in dashboard.project_heading.empty_text.text()
    assert dashboard.recent_items == [] and dashboard.result_rows == []


def test_the_open_project_shows_its_name_and_folder(dashboard):
    dashboard.set_projects(_project(1), [_project(1)], [])
    card = dashboard.project_heading
    assert card.pages.currentIndex() == 1 and card.name.text() == "Project 1"
    assert card.path.text() == "D:/work/Project 1"


def test_the_dashboard_has_no_buttons(dashboard):
    from PyQt6.QtWidgets import QAbstractButton

    dashboard.set_projects(_project(1), [_project(1), _project(2)], [_record(1)])
    assert dashboard.findChildren(QAbstractButton) == []
    dashboard.set_projects(None, [], [])
    assert dashboard.findChildren(QAbstractButton) == []


def test_only_the_last_three_projects_are_listed_with_their_folders(dashboard):
    dashboard.set_projects(None, [_project(n) for n in range(1, 6)], [])
    assert [item.project.name for item in dashboard.recent_items] == ["Project 1", "Project 2", "Project 3"]
    opened = []
    dashboard.open_recent.connect(opened.append)
    _click(dashboard.recent_items[1])
    assert opened == ["D:/work/Project 2"]


def test_the_open_projects_recent_results_are_listed(dashboard):
    records = [_record(n) for n in range(12)]
    dashboard.set_projects(_project(1), [_project(1), _project(2)], records)
    assert len(dashboard.result_rows) == 8  # the latest eight, of the open project only
    texts = [label.text() for label in dashboard.result_rows[0].labels]
    assert texts[0] == "Vegetation · NDVI, EVI"
    assert texts[1] == "14 Nov 2026, 12:30  ·  saved" and "NDVI mean: 0.421" in texts


def test_updating_replaces_the_lists(dashboard):
    dashboard.set_projects(_project(1), [_project(1), _project(2)], [_record(1)])
    dashboard.set_projects(None, [_project(3)], [])
    assert [item.project.name for item in dashboard.recent_items] == ["Project 3"] and dashboard.result_rows == []


def test_category_labels():
    assert category_label("LULC") == "Land cover" and category_label("Water") == "Water"


def test_the_open_projects_name_comes_right_after_the_welcome(dashboard):
    from backend.dto.user_dto import UserDTO

    dashboard.set_user(UserDTO(id="u1", username="ayesha", email="a@example.com", full_name="Ayesha Khan",
                               role="user", is_active=True, email_verified=True))
    dashboard.set_projects(_project(1), [_project(1)], [])
    dashboard.resize(1200, 800)
    dashboard.show()
    QApplication.processEvents()
    greeting, name = dashboard.greeting, dashboard.project_heading.name
    below = name.mapTo(dashboard, name.rect().topLeft()).y() - greeting.mapTo(dashboard, greeting.rect().bottomLeft()).y()
    assert greeting.text() == "Welcome, Ayesha" and name.text() == "Project 1"
    assert 0 <= below <= 60  # the next thing under the welcome
    assert name.mapTo(dashboard, name.rect().topLeft()).x() == greeting.mapTo(dashboard, greeting.rect().topLeft()).x()
    dashboard.hide()


def _shown(dashboard, width=1300, height=820):
    dashboard.set_projects(_project(1), [_project(n) for n in range(1, 4)], [])
    dashboard.resize(width, height)
    dashboard.show()
    QApplication.processEvents()


def _left(widget, dashboard) -> int:
    return widget.mapTo(dashboard, widget.rect().topLeft()).x()


def _right(widget, dashboard) -> int:
    return widget.mapTo(dashboard, widget.rect().topRight()).x()


@pytest.mark.parametrize("width", [1100, 1600])
def test_recent_projects_are_on_the_right_edge_of_the_dashboard(dashboard, width):
    _shown(dashboard, width)
    panel, margin = dashboard.recent_panel, 36
    assert dashboard.width() - _right(panel, dashboard) <= margin + 20  # against the right edge (scroll bar room)
    assert _left(panel, dashboard) > _right(dashboard.project_heading, dashboard)  # to the right of the rest
    assert panel.mapTo(dashboard, panel.rect().topLeft()).y() <= dashboard.greeting.mapTo(
        dashboard, dashboard.greeting.rect().bottomLeft()).y()  # level with the top of the page
    dashboard.hide()


def test_the_rest_starts_at_the_left_of_the_page(dashboard):
    _shown(dashboard, 1600)
    lefts = {_left(w, dashboard) for w in (dashboard.greeting, dashboard.project_heading, dashboard.results_panel)}
    assert len(lefts) == 1 and lefts.pop() <= 40  # one left edge, at the page margin: not centred
    dashboard.hide()


def test_the_results_come_right_under_the_projects_name(dashboard):
    dashboard.set_projects(_project(1), [_project(1)], [_record(1), _record(2)])
    dashboard.resize(1300, 820)
    dashboard.show()
    QApplication.processEvents()
    heading, panel = dashboard.project_heading, dashboard.results_panel
    heading_bottom = heading.mapTo(dashboard, heading.rect().bottomLeft()).y()
    panel_top = panel.mapTo(dashboard, panel.rect().topLeft()).y()
    assert 0 <= panel_top - heading_bottom <= 40
    dashboard.hide()


def test_without_a_project_no_results_are_listed(dashboard):
    dashboard.set_projects(None, [_project(1)], [_record(1)])
    assert dashboard.result_rows == []
    note = dashboard.results_list.itemAt(0).widget().text()
    assert note == "Open a project to see its analysis results here."
    dashboard.set_projects(_project(1), [_project(1)], [])
    assert dashboard.results_list.itemAt(0).widget().text() == "Results of the analyses you run in Project 1 appear here."


@pytest.mark.parametrize("open_project", [True, False])
def test_all_text_on_the_dashboard_is_left_aligned(dashboard, open_project):
    from PyQt6.QtWidgets import QLabel

    current = _project(1) if open_project else None
    dashboard.set_projects(current, [_project(1), _project(2)], [_record(1), _record(2)])
    labels = [label for label in dashboard.findChildren(QLabel) if label.text()]
    assert len(labels) > 5
    for label in labels:
        horizontal = label.alignment() & Qt.AlignmentFlag.AlignHorizontal_Mask
        assert horizontal in (Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignLeading), label.text()


# ------------------------------------------------------------------ a result row
DATASET = "downloads/Sentinel-2_76.9812_14.1309_2026-08-17_2026-11-17/Sentinel-2_76.9812_14.1309_2026-08-17_2026-11-17.tif"


def _full_record(**changes) -> AnalysisRecordDTO:
    values = dict(id="r1", category="Water", processes=["NDWI"], saved=False, created_at="2026-11-18T15:08:00",
                  metrics={"NDWI mean": -0.4281, "NDWI min": -0.91, "NDWI max": 0.62, "Water area (km²)": 3.1},
                  dataset=DATASET, device="CPU", seconds=2.46)
    values.update(changes)
    return AnalysisRecordDTO(**values)


def test_a_result_row_shows_what_ran_on_which_dataset_and_its_numbers(app):
    from frontend.views.dashboard_view import ResultRow

    row = ResultRow(_full_record())
    texts = [label.text() for label in row.labels]
    assert texts[:3] == ["Water · NDWI", "18 Nov 2026, 15:08  ·  not saved", "Ran on the CPU in 2.5 s"]
    assert texts[3:5] == ["Sentinel-2  ·  17 Aug – 17 Nov 2026", "14.1309° N, 76.9812° E"]
    assert texts[5:] == ["NDWI mean: -0.428", "NDWI min: -0.91", "NDWI max: 0.62", "+1 more (point at the row)"]
    assert "Water area (km²): 3.1" in row.toolTip()  # all the numbers


def test_a_result_row_with_little_recorded_still_reads_well(app):
    from frontend.views.dashboard_view import ResultRow

    row = ResultRow(_full_record(metrics={}, dataset="", device="", seconds=0.0))
    texts = [label.text() for label in row.labels]
    assert texts == ["Water · NDWI", "18 Nov 2026, 15:08  ·  not saved", "Dataset not recorded", "No numbers recorded"]
    assert row.toolTip() == "No numbers recorded"


def test_a_result_row_fills_its_width_in_three_columns(app):
    from frontend.views.dashboard_view import ResultRow

    row = ResultRow(_full_record())
    row.resize(720, 90)
    row.show()
    QApplication.processEvents()
    title, dataset, number = row.labels[0], row.labels[3], row.labels[5]
    assert title.x() < dataset.x() < number.x()          # side by side, not one under the other
    assert number.x() > row.width() // 2                  # the right half of the row is used
    assert all(label.alignment() & Qt.AlignmentFlag.AlignLeft for label in row.labels)
    row.hide()


def test_dataset_names_and_numbers_are_summarised():
    from frontend.views.dashboard_view import dataset_summary, format_date_range, format_number, run_summary

    assert dataset_summary(r"C:\data\scene.tif") == ("scene", "")      # not a download's name
    assert dataset_summary("") == ("", "")
    assert dataset_summary("Landsat-8_-58.4_-34.6_2025-12-01_2026-01-31.tif") == (
        "Landsat-8  ·  01 Dec 2025 – 31 Jan 2026", "34.6000° S, 58.4000° W")
    assert format_date_range("2026-08-17", "2026-11-17") == "17 Aug – 17 Nov 2026"
    assert [format_number(v) for v in (-0.42813, 1530.2, 3.1)] == ["-0.428", "1,530", "3.1"]
    assert run_summary(AnalysisRecordDTO("r", "W", device="GPU: NVIDIA RTX 3060")) == "Ran on the GPU: NVIDIA RTX 3060"
    assert run_summary(AnalysisRecordDTO("r", "W")) == ""


# ------------------------------------------------------------------ all the results
def test_the_results_dialog_lists_every_result_of_the_project_newest_first(app):
    from PyQt6.QtWidgets import QDialog, QDialogButtonBox

    from frontend.views.dashboard_view import AnalysisResultsDialog

    records = [_full_record(id=f"r{n}", created_at=f"2026-11-{18 - n:02d}T10:00:00") for n in range(7)]
    dialog = AnalysisResultsDialog("Lahore 2024", records)
    assert dialog.isModal() and dialog.windowTitle() == "Analysis results — Lahore 2024"
    assert [row.labels[1].text().split("  ·  ")[0] for row in dialog.rows][:2] == ["18 Nov 2026, 10:00",
                                                                                  "17 Nov 2026, 10:00"]
    assert len(dialog.rows) == 7
    dialog.buttons.button(QDialogButtonBox.StandardButton.Close).click()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_the_results_dialog_scrolls_when_the_results_do_not_fit(app):
    from PyQt6.QtWidgets import QScrollArea

    from frontend.views.dashboard_view import AnalysisResultsDialog

    dialog = AnalysisResultsDialog("Lahore 2024", [_full_record(id=f"r{n}") for n in range(30)])
    dialog.resize(800, 480)
    dialog.show()
    QApplication.processEvents()
    assert dialog.findChild(QScrollArea).verticalScrollBar().maximum() > 0
    dialog.close()
