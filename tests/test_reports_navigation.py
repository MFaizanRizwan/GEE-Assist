"""The signed-in window opens the Reports page from the dashboard, the View menu and an explanation."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.dto.project_dto import ProjectDTO  # noqa: E402
from backend.dto.user_dto import UserDTO  # noqa: E402

app = QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    from frontend.views import home_window  # after the QApplication (the window embeds a web map)

    user = UserDTO(id="u1", username="ayesha", email="a@example.com", full_name="Ayesha Khan", role="user",
                   is_active=True, email_verified=True)
    facade = MagicMock(spec=IBusinessFacade)
    facade.get_current_user.return_value = user
    facade.get_current_project.return_value = ProjectDTO("p1", "P", "C:/work/P")
    facade.list_projects.return_value = []
    facade.list_explanations.return_value = []
    facade.check_app_version.return_value = None
    facade.get_profile_photo.return_value = None
    home = home_window.HomeWindow(facade, user)
    created = []
    home.reports.create_report = lambda path="": created.append(path)
    yield home, created
    home.terminal.shutdown()
    home.deleteLater()


def test_show_reports_opens_the_reports_page_without_creating_one(window):
    home, created = window
    home.show_reports()
    assert home.current_page() is home.reports and created == []


def test_view_reports_opens_the_reports_page(window):
    home, _ = window
    home.menu_bar.view_reports.trigger()
    assert home.current_page() is home.reports


def test_an_explanations_pdf_report_is_created_on_the_reports_page(window):
    home, created = window
    home.explanation.report_requested.emit("C:/work/P/explanation/result_explanation.md")
    assert home.current_page() is home.reports
    assert created == ["C:/work/P/explanation/result_explanation.md"]
