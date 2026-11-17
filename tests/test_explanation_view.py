"""The AI explanation page: metadata before and after, Gemini's answer, errors (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.dto.explanation_dto import (  # noqa: E402
    ExplanationDTO,
    ExplanationRequestDTO,
    LayerInfoDTO,
    ProcessInfoDTO,
    RasterMetadataDTO,
)
from backend.dto.result_dto import ResultDTO  # noqa: E402
from backend.exceptions import LLMServiceError  # noqa: E402
from frontend.views.explanation_view import ExplanationView, sent_text  # noqa: E402

app = QApplication.instance() or QApplication([])

UNSAVED = ResultDTO("r1", "Vegetation", ["NDVI"], {"NDVI mean": 0.42}, "C:/temp/result.tif", device="CPU",
                    seconds=1.5)
SAVED = replace(UNSAVED, output_path="C:/Project 1/analysis/result.tif", saved=True)
REQUEST = ExplanationRequestDTO(
    SAVED, "Vegetation", "Vegetation health", (ProcessInfoDTO("NDVI", "Normalized Difference Vegetation Index"),),
    {"savi_l": 0.5},
    before=RasterMetadataDTO("Sentinel-2_73_31_2024-06-01_2024-06-30", "C:/d.tif", satellite="Sentinel-2",
                             start_date="2024-06-01", end_date="2024-06-30", bands=("B4", "B8")),
    after=RasterMetadataDTO("result", SAVED.output_path, bands=("NDVI",), width=50, height=40),
    layers=(LayerInfoDTO("NDVI", "NDVI", legend="red to green over -0.2 to 0.8"),), previews=(b"png",))
ANSWER = ExplanationDTO("## Summary\n\nThe fields are **healthy**.", "gemini-test", True, REQUEST,
                        "C:/Project 1/analysis/result_explanation.md")


def _wait(condition, timeout_ms=3000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    assert condition()


@pytest.fixture
def page():
    facade = MagicMock(spec=IBusinessFacade)
    facade.prepare_explanation.return_value = REQUEST
    facade.explain_analysis_result.return_value = ANSWER
    view = ExplanationView(facade)
    view.resize(1100, 700)
    return view, facade


def test_the_result_is_saved_its_metadata_shown_and_gemini_answers(page):
    view, facade = page
    saved, ready = [], []
    view.result_saved.connect(saved.append)
    view.explanation_ready.connect(ready.append)
    view.explain(UNSAVED)
    _wait(lambda: ready)

    facade.prepare_explanation.assert_called_once_with(UNSAVED)
    facade.explain_analysis_result.assert_called_once_with(REQUEST)
    assert saved == [SAVED]  # the Analysis page learns the result is now saved
    metadata = view.metadata_view.toPlainText()
    for text in ("ANALYSIS", "Vegetation health", "NDVI (Normalized Difference Vegetation Index)", "savi_l = 0.5",
                 "BEFORE THE ANALYSIS: DATASET", "Sentinel-2", "2024-06-01 to 2024-06-30",
                 "AFTER THE ANALYSIS: RESULT", "50 × 40 pixels", "red to green over -0.2 to 0.8", "NDVI mean"):
        assert text in metadata
    assert "The fields are healthy." in view.answer_view.toPlainText()
    assert "Sent to Gemini: result.tif (saved in the project), 1 layer preview" in view.sent_label.text()
    assert "result_explanation.md" in view.banner.text()
    assert view.copy_button.isEnabled() and view.folder_button.isEnabled() and not view.busy


def test_a_gemini_error_is_shown_and_can_be_retried(page):
    view, facade = page
    facade.explain_analysis_result.side_effect = [LLMServiceError("Gemini is busy right now."), ANSWER]
    view.explain(UNSAVED)
    _wait(lambda: not view.busy and view.banner.text())
    assert view.banner.text() == "Gemini is busy right now."
    assert view.again_button.isEnabled() and view.again_button.text() == "Try again"
    assert not view.copy_button.isEnabled()

    view.again_button.click()
    _wait(lambda: view.explanation is not None)
    assert facade.prepare_explanation.call_count == 1  # already saved and prepared: only Gemini is asked again
    assert view.again_button.text() == "Explain again"


def test_copy_puts_the_explanation_on_the_clipboard(page):
    view, _ = page
    view.explain(UNSAVED)
    _wait(lambda: view.explanation is not None)
    view.copy_button.click()
    assert QApplication.clipboard().text() == ANSWER.text


def test_back_asks_for_the_analysis_page(page):
    view, _ = page
    asked = []
    view.back_requested.connect(lambda: asked.append(True))
    view.back_button.click()
    assert asked == [True]


def test_an_answer_for_an_earlier_result_is_ignored(page):
    view, facade = page
    view.explain(UNSAVED)
    view.explain(replace(UNSAVED, id="r2"))  # a second explanation before the first came back
    _wait(lambda: view.explanation is not None)
    QTest.qWait(50)
    assert facade.explain_analysis_result.call_count == 1


def test_the_sent_line_says_when_gemini_refused_the_geotiff():
    text = sent_text(replace(ANSWER, tif_attached=False))
    assert text.startswith("Saved in the project: result.tif. Gemini refused the GeoTIFF, so it was sent 1 layer")
    text = sent_text(replace(ANSWER, tif_attached=False, previews_attached=False))
    assert "so it was sent the metadata only" in text


def test_a_saved_explanation_can_be_turned_into_a_pdf_report(page):
    view, _ = page
    assert not view.report_button.isEnabled()  # nothing explained yet
    view.explain(UNSAVED)
    _wait(lambda: view.explanation is not None)
    asked = []
    view.report_requested.connect(asked.append)
    view.report_button.click()
    assert asked == [ANSWER.saved_path]


def test_an_explanation_that_could_not_be_saved_has_no_report(page):
    view, facade = page
    facade.explain_analysis_result.return_value = replace(ANSWER, saved_path="")
    view.explain(UNSAVED)
    _wait(lambda: view.explanation is not None)
    assert not view.report_button.isEnabled()
