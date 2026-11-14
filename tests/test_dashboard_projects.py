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


def test_without_a_project_it_offers_to_create_or_open_one(dashboard):
    asked = []
    dashboard.new_project.connect(lambda: asked.append("new"))
    dashboard.open_project.connect(lambda: asked.append("open"))
    assert dashboard.project_card.pages.currentIndex() == 0
    dashboard.project_card.new_button.click()
    dashboard.project_card.open_button.click()
    assert asked == ["new", "open"]
    assert dashboard.recent_items == [] and dashboard.result_rows == []


def test_the_open_project_and_its_actions(dashboard):
    asked = []
    for name in ("rename_project", "move_project", "show_project_folder", "close_project"):
        getattr(dashboard, name).connect(lambda name=name: asked.append(name))
    dashboard.set_projects(_project(1), [_project(1)], [])
    card = dashboard.project_card
    assert card.pages.currentIndex() == 1 and card.name.text() == "Project 1"
    assert card.path.text() == "D:/work/Project 1"
    for button in (card.rename_button, card.move_button, card.folder_button, card.close_button):
        button.click()
    assert asked == ["rename_project", "move_project", "show_project_folder", "close_project"]


def test_only_the_last_three_projects_are_listed_with_their_folders(dashboard):
    dashboard.set_projects(None, [_project(n) for n in range(1, 6)], [])
    assert [item.project.name for item in dashboard.recent_items] == ["Project 1", "Project 2", "Project 3"]
    opened = []
    dashboard.open_recent.connect(opened.append)
    _click(dashboard.recent_items[1])
    assert opened == ["D:/work/Project 2"]


def test_recent_results_of_the_last_three_projects(dashboard):
    results = [(_project(n), [_record(10 * n + i) for i in range(5)]) for n in range(1, 5)]
    dashboard.set_projects(_project(1), [p for p, _ in results], results)
    assert len(dashboard.result_rows) == 3 * 3  # three projects, three results each
    texts = [label.text() for label in dashboard.result_rows[0].findChildren(type(dashboard.greeting))]
    assert texts[0] == "Vegetation · NDVI, EVI"
    assert "14 Nov 2026, 12:30" in texts[1] and "NDVI mean: 0.421" in texts[1] and "saved" in texts[1]


def test_updating_replaces_the_lists(dashboard):
    dashboard.set_projects(None, [_project(1), _project(2)], [(_project(1), [_record(1)])])
    dashboard.set_projects(None, [_project(3)], [])
    assert [item.project.name for item in dashboard.recent_items] == ["Project 3"] and dashboard.result_rows == []


def test_category_labels():
    assert category_label("LULC") == "Land cover" and category_label("Water") == "Water"
