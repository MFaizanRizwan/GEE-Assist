"""The signed-in window: the AI explanation page, and asking for feedback after it (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO  # noqa: E402
from backend.dto.project_dto import ProjectDTO  # noqa: E402
from backend.dto.result_dto import ResultDTO  # noqa: E402
from backend.dto.user_dto import UserDTO  # noqa: E402
from backend.exceptions import LLMServiceError  # noqa: E402

app = QApplication.instance() or QApplication([])

RESULT = ResultDTO("r1", "Vegetation", ["NDVI"], {"NDVI mean": 0.4}, "C:/temp/result.tif")
SAVED = replace(RESULT, output_path="C:/work/P/analysis/result.tif", saved=True)
REQUEST = ExplanationRequestDTO(SAVED, "Vegetation", "Vegetation")
ANSWER = ExplanationDTO("## Summary\nHealthy.", "gemini-test", True, REQUEST, "C:/work/P/analysis/result_explanation.md")


def _texts():
    from frontend.views import home_window
    return home_window


def _wait(condition, timeout_ms=3000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    assert condition()


@pytest.fixture
def window(monkeypatch):
    from frontend.views import home_window

    monkeypatch.setattr(home_window, "FEEDBACK_DELAY_MS", 0)
    user = UserDTO(id="u1", username="ayesha", email="a@example.com", full_name="Ayesha Khan", role="user",
                   is_active=True, email_verified=True)
    facade = MagicMock(spec=IBusinessFacade)
    facade.get_current_user.return_value = user
    facade.get_current_project.return_value = ProjectDTO("p1", "P", "C:/work/P")
    facade.list_projects.return_value = []
    facade.list_analysis_datasets.return_value = []
    facade.list_downloads.return_value = []
    facade.get_chunk_size_mb.return_value = 500
    facade.check_app_version.return_value = None
    facade.get_profile_photo.return_value = None
    facade.prepare_explanation.return_value = REQUEST
    facade.explain_analysis_result.return_value = ANSWER
    home = home_window.HomeWindow(facade, user)
    asked = []
    home.feedback_prompt = lambda parent, reason: asked.append(reason) or "feedback"
    home.isVisible = lambda: True  # as on screen (showing it offscreen would start the web map)
    yield home, facade, asked
    home.terminal.shutdown()
    home.deleteLater()


def test_explain_with_ai_opens_the_explanation_page(window):
    home, facade, _ = window
    home.analysis.result = RESULT
    home.analysis.explain()
    assert home.current_page() is home.explanation
    _wait(lambda: home.explanation.explanation is not None)
    facade.prepare_explanation.assert_called_once_with(RESULT)
    assert home.analysis.result == SAVED  # the Analysis page shows it as saved now


def test_feedback_is_asked_for_after_every_explanation(window):
    home, _, asked = window
    home.show_explanation(RESULT)
    _wait(lambda: asked)
    assert asked == [_texts().AFTER_EXPLANATION]
    home.explanation.explain_again()
    _wait(lambda: len(asked) == 2)


def test_feedback_is_not_asked_for_when_gemini_fails(window):
    home, facade, asked = window
    facade.explain_analysis_result.side_effect = LLMServiceError("Gemini is busy right now.")
    home.show_explanation(RESULT)
    _wait(lambda: not home.explanation.busy)
    QTest.qWait(30)
    assert asked == []


def test_going_from_the_explanation_to_the_dashboard_asks_for_feedback(window):
    home, _, asked = window
    home.show_explanation(RESULT)
    _wait(lambda: asked)  # after the explanation
    home.show_dashboard()
    _wait(lambda: len(asked) == 2)
    assert asked[1] == _texts().BACK_FROM_EXPLANATION
    assert home.current_page() is home.dashboard


def test_other_pages_go_to_the_dashboard_without_asking(window):
    home, _, asked = window
    home.show_analysis()
    home.show_dashboard()
    QTest.qWait(30)
    assert asked == []


def test_back_from_the_explanation_goes_to_the_analysis_page_without_asking(window):
    home, facade, asked = window
    facade.prepare_explanation.side_effect = LLMServiceError("not now")  # no explanation made
    home.show_explanation(RESULT)
    _wait(lambda: not home.explanation.busy)
    home.explanation.back_button.click()
    QTest.qWait(30)
    assert home.current_page() is home.analysis and asked == []


def test_only_one_feedback_modal_at_a_time(window):
    home, _, asked = window

    def prompt(parent, reason):
        asked.append(reason)
        assert home.ask_for_feedback("again") is None  # e.g. the delayed one while this is open
        return None

    home.feedback_prompt = prompt
    home.ask_for_feedback("first")
    assert asked == ["first"]


def test_help_menu_asks_for_feedback(window):
    home, _, asked = window
    home.menu_bar.give_feedback.trigger()
    assert asked == [""]


# ------------------------------------------------------------------ after an analysis
def test_coming_back_to_the_dashboard_after_an_analysis_asks_for_feedback(window):
    home, _, asked = window
    home.show_analysis()
    home.analysis.analysis_finished.emit(RESULT)
    home.show_dashboard()
    _wait(lambda: asked)
    assert asked == [_texts().AFTER_ANALYSIS] and home.current_page() is home.dashboard


def test_the_analysis_is_asked_about_once(window):
    home, _, asked = window
    home.show_analysis()
    home.analysis.analysis_finished.emit(RESULT)
    home.show_dashboard()
    _wait(lambda: asked)
    home.show_downloads()
    home.show_dashboard()  # no new analysis since
    QTest.qWait(30)
    assert asked == [_texts().AFTER_ANALYSIS]


def test_any_page_leading_back_to_the_dashboard_counts(window):
    home, _, asked = window
    home.analysis.analysis_finished.emit(RESULT)
    home.show_downloads()  # e.g. went to check a download first
    home.show_dashboard()
    _wait(lambda: asked)
    assert asked == [_texts().AFTER_ANALYSIS]


def test_analysis_then_explanation_then_dashboard_asks_once_on_the_way_back(window):
    home, _, asked = window
    home.analysis.analysis_finished.emit(RESULT)
    home.show_explanation(RESULT)
    _wait(lambda: asked)  # after the explanation
    home.show_dashboard()
    _wait(lambda: len(asked) == 2)
    QTest.qWait(30)
    assert asked == [_texts().AFTER_EXPLANATION, _texts().BACK_FROM_EXPLANATION]


def test_no_analysis_no_question(window):
    home, _, asked = window
    home.show_analysis()  # opened, but nothing ran
    home.show_dashboard()
    QTest.qWait(30)
    assert asked == []
