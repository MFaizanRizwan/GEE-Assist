"""The side bar's AI Explanation: choose a saved result of the open project and explain it (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO  # noqa: E402
from backend.dto.project_dto import ProjectDTO  # noqa: E402
from backend.dto.result_dto import ResultDTO  # noqa: E402
from backend.dto.user_dto import UserDTO  # noqa: E402
from backend.exceptions import AnalysisError  # noqa: E402

app = QApplication.instance() or QApplication([])

PROJECT = ProjectDTO("p1", "Lahore 2024", "C:/work/Lahore 2024")
NEWER = ResultDTO("r2", "Water", ["NDWI"], output_path="C:/work/Lahore 2024/analysis/b.tif", saved=True,
                  created_at="2024-07-02T09:30:00")
OLDER = ResultDTO("r1", "Vegetation", ["NDVI"], output_path="C:/work/Lahore 2024/analysis/a.tif", saved=True,
                  created_at="2024-06-01T08:00:00")


@pytest.fixture
def window():
    from frontend.views import home_window  # after the QApplication (the window embeds a web map)

    user = UserDTO(id="u1", username="ayesha", email="a@example.com", full_name="Ayesha Khan", role="user",
                   is_active=True, email_verified=True)
    facade = MagicMock(spec=IBusinessFacade)
    facade.get_current_user.return_value = user
    facade.get_current_project.return_value = PROJECT
    facade.list_projects.return_value = []
    facade.list_saved_results.return_value = [NEWER, OLDER]
    # The real explanation page is opened in one test: it gets a real request and answer, not mocks.
    request = ExplanationRequestDTO(OLDER, "Vegetation", "Vegetation")
    facade.prepare_explanation.return_value = request
    facade.explain_analysis_result.return_value = ExplanationDTO("## Summary\nGreen.", "gemini-test", True, request)
    facade.check_app_version.return_value = None
    facade.get_profile_photo.return_value = None
    home = home_window.HomeWindow(facade, user)
    explained, asked = [], []
    home.show_explanation = explained.append
    home.result_chooser = lambda results, project, parent: asked.append((results, project)) or results[1]
    yield home, facade, explained, asked
    home.terminal.shutdown()
    home.deleteLater()


def test_the_side_bar_has_an_ai_explanation_button_with_its_own_icon(window):
    from frontend.widgets.side_icons import ExplainIcon

    home, *_ = window
    assert home.explain_button.parent() is home.side_bar
    assert isinstance(home.explain_button.icon_drawing, ExplainIcon)
    home.side_bar.set_expanded(True, animate=False)
    assert home.explain_button.text() == "AI Explanation"
    buttons = [home.query_input_button, home.downloads_button, home.analysis_button, home.explain_button]
    assert [b.y() for b in buttons] == sorted(b.y() for b in buttons)  # right after Analysis


def test_it_asks_which_of_the_projects_results_to_explain(window):
    home, facade, explained, asked = window
    home.explain_button.click()
    assert asked == [([NEWER, OLDER], "Lahore 2024")]
    assert explained == [OLDER]  # the one chosen, as saved (it is not saved again)


def test_cancelling_the_choice_explains_nothing(window):
    home, _, explained, _ = window
    home.result_chooser = lambda results, project, parent: None
    home.explain_button.click()
    assert explained == []


def test_without_a_project_it_asks_to_create_or_open_one(window, monkeypatch):
    from frontend.views.home_window import EXPLANATION_NEEDS_PROJECT

    home, facade, explained, asked = window
    facade.get_current_project.return_value = None
    reasons = []
    monkeypatch.setattr(home, "ask_for_project", lambda why: reasons.append(why))  # cancelled
    home.explain_button.click()
    assert reasons == [EXPLANATION_NEEDS_PROJECT] and asked == [] and explained == []


def test_a_project_without_results_offers_the_analysis_page(window, monkeypatch):
    home, facade, explained, asked = window
    facade.list_saved_results.return_value = []
    offered = []
    monkeypatch.setattr(home, "offer_analysis", lambda name: offered.append(name) or True)
    home.explain_button.click()
    assert offered == ["Lahore 2024"] and asked == [] and home.current_page() is home.analysis

    monkeypatch.setattr(home, "offer_analysis", lambda name: False)  # Close
    home.show_dashboard()
    home.explain_button.click()
    assert home.current_page() is home.dashboard


def test_a_listing_error_is_shown(window, monkeypatch):
    from frontend.views import home_window

    home, facade, explained, _ = window
    facade.list_saved_results.side_effect = AnalysisError("Analysis is not set up in this build.")
    warned = []
    monkeypatch.setattr(home_window.QMessageBox, "warning", lambda parent, title, text: warned.append(text))
    home.explain_button.click()
    assert warned == ["Analysis is not set up in this build."] and explained == []


def test_the_button_stays_in_the_side_bar_on_the_explanation_page(window):
    from frontend.views.home_window import HomeWindow

    home, *_ = window
    HomeWindow.show_explanation(home, OLDER)  # the real page, not the test's stand-in
    assert home.current_page() is home.explanation and home.explain_button.isVisibleTo(home)
    home.show_dashboard()
    assert home.explain_button.isVisibleTo(home)


def test_the_explanation_pages_button_is_highlighted_on_it(window):
    from frontend.views.home_window import HomeWindow

    home, *_ = window
    HomeWindow.show_explanation(home, OLDER)
    assert home.explain_button.is_current() and not home.analysis_button.is_current()
    home.show_analysis()  # e.g. "Back to analysis"
    assert home.analysis_button.is_current() and not home.explain_button.is_current()
