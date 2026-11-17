"""The dialog asking which saved result (.tif) of the project to explain (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from backend.dto.result_dto import ResultDTO  # noqa: E402
from frontend.views.result_picker_dialog import ResultPickerDialog, item_text, result_title  # noqa: E402

app = QApplication.instance() or QApplication([])

NEWER = ResultDTO("r2", "Water", ["NDWI", "MNDWI"], output_path="C:/p/analysis/b.tif", created_at="2024-07-02T09:30:00",
                  saved=True)
OLDER = ResultDTO("r1", "Vegetation", ["NDVI"], output_path="C:/p/analysis/a.tif", created_at="2024-06-01T08:00:00",
                  saved=True)


def test_each_result_shows_its_analysis_file_and_date():
    assert item_text(NEWER) == "Water: NDWI, MNDWI\nb.tif  ·  2024-07-02 09:30"
    assert result_title(ResultDTO("x", "", output_path="C:/p/analysis/x.tif")) == "Analysis result"


def test_the_newest_result_is_chosen_first_and_another_can_be_picked():
    dialog = ResultPickerDialog([NEWER, OLDER], "Project 1")
    assert dialog.list.count() == 2 and dialog.chosen() is NEWER and dialog.explain_button.isEnabled()
    dialog.list.setCurrentRow(1)
    dialog.explain_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.chosen() is OLDER


def test_double_clicking_a_result_explains_it():
    dialog = ResultPickerDialog([NEWER, OLDER])
    dialog.list.itemDoubleClicked.emit(dialog.list.item(1))
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.chosen() is OLDER


def test_cancel_chooses_nothing():
    dialog = ResultPickerDialog([NEWER])
    dialog.cancel_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_nothing_to_choose_cannot_be_accepted():
    dialog = ResultPickerDialog([])
    assert dialog.chosen() is None and not dialog.explain_button.isEnabled()
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
