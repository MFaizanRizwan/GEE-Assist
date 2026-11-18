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

    dashboard.set_projects(_project(1), [_project(1), _project(2)], [(_project(1), [_record(1)])])
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
