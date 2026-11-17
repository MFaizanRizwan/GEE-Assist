"""The Reports page: list explanations, create their PDF reports, export them (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.dto.project_dto import ProjectDTO  # noqa: E402
from backend.dto.report_dto import ExplanationFileDTO  # noqa: E402
from backend.exceptions import ReportError  # noqa: E402
from frontend.views.reports_view import NO_EXPLANATIONS, NO_PROJECT, ReportsView, item_text  # noqa: E402

app = QApplication.instance() or QApplication([])


def _wait(condition, timeout_ms=3000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    assert condition()


@pytest.fixture
def page(tmp_path):
    project = ProjectDTO("p1", "Project 1", str(tmp_path / "Project 1"))
    explanation_dir = tmp_path / "Project 1" / "explanation"
    explanation_dir.mkdir(parents=True)
    newer = ExplanationFileDTO(str(explanation_dir / "b_explanation.md"), "AI explanation: Water (NDWI)", "b.tif",
                               "2024-07-02T09:30:00")
    older = ExplanationFileDTO(str(explanation_dir / "a_explanation.md"), "AI explanation: Vegetation (NDVI)",
                               "a.tif", "2024-06-01T08:00:00")
    files = {"list": [newer, older]}
    facade = MagicMock(spec=IBusinessFacade)
    facade.get_current_project.return_value = project
    facade.list_explanations.side_effect = lambda: list(files["list"])
    def create(explanation_path):  # as the backend does: the PDF in the project's reports folder
        target = tmp_path / "Project 1" / "reports" / (os.path.basename(explanation_path)[:-3] + ".pdf")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.7 report")
        files["list"] = [replace(item, report_path=str(target)) if item.path == explanation_path else item
                         for item in files["list"]]
        return str(target)

    facade.create_report.side_effect = create
    facade.export_report.side_effect = lambda pdf, destination: destination
    view = ReportsView(facade)
    view.refresh()
    return view, facade, tmp_path


def test_the_projects_explanations_are_listed_newest_first(page):
    view, _, _ = page
    assert view.list.count() == 2
    assert view.list.item(0).text().startswith("AI explanation: Water (NDWI)\nb.tif  ·  2024-07-02 09:30")
    assert view.current().result_name == "b.tif"
    assert view.create_button.isEnabled() and view.create_button.text() == "Create PDF report"
    assert not view.export_button.isEnabled() and not view.open_button.isEnabled()  # no PDF yet


def test_creating_a_report_keeps_a_real_pdf_in_the_project(page):
    view, facade, tmp_path = page
    view.list.setCurrentRow(1)
    view.create_button.click()
    _wait(lambda: not view.busy)

    facade.create_report.assert_called_once_with(view.explanations[1].path)
    saved = tmp_path / "Project 1" / "reports" / "a_explanation.pdf"
    assert saved.read_bytes().startswith(b"%PDF-")
    assert view.current().path.endswith("a_explanation.md")  # still the one chosen
    assert "PDF ready" in view.list.item(1).text()
    assert view.banner.text().startswith(f"Report saved to {saved}")
    assert view.export_button.isEnabled() and view.create_button.text() == "Create PDF again"


def test_a_report_is_exported_where_the_user_chooses(page):
    view, facade, tmp_path = page
    view.create_report()
    _wait(lambda: view._report_of_current())
    asked = []
    view.choose_export_path = lambda suggested: asked.append(suggested) or str(tmp_path / "usb" / "report.pdf")
    view.export_button.click()
    assert asked[0].endswith("b_explanation.pdf")  # suggested in Documents under the report's name
    facade.export_report.assert_called_once_with(view.current().report_path, str(tmp_path / "usb" / "report.pdf"))
    assert view.banner.text() == f"Report exported to {tmp_path / 'usb' / 'report.pdf'}"


def test_cancelling_the_export_does_nothing(page):
    view, facade, _ = page
    view.create_report()
    _wait(lambda: view._report_of_current())
    view.choose_export_path = lambda suggested: ""
    view.export_button.click()
    facade.export_report.assert_not_called()


def test_an_export_error_is_shown(page):
    view, facade, _ = page
    view.create_report()
    _wait(lambda: view._report_of_current())
    facade.export_report.side_effect = ReportError("Could not export the report to E:/r.pdf: Access is denied")
    view.choose_export_path = lambda suggested: "E:/r.pdf"
    view.export_button.click()
    assert "Access is denied" in view.banner.text()


def test_a_report_can_be_created_for_a_given_explanation(page):
    view, facade, _ = page
    path = view.explanations[1].path
    view.create_report(path)  # e.g. from the AI explanation page
    _wait(lambda: not view.busy)
    assert view.current().path == path and view.current().report_path


def test_a_build_error_is_shown(page):
    view, facade, _ = page
    facade.create_report.side_effect = ReportError("The explanation b_explanation.md cannot be read")
    view.create_report()
    _wait(lambda: not view.busy)
    assert "cannot be read" in view.banner.text() and view.create_button.isEnabled()


def test_without_a_project_or_explanations_the_page_says_what_to_do(page):
    view, facade, _ = page
    facade.list_explanations.side_effect = lambda: []
    view.refresh()
    assert view.empty_label.text() == NO_EXPLANATIONS and not view.create_button.isEnabled()
    facade.get_current_project.return_value = None
    view.refresh()
    assert view.empty_label.text() == NO_PROJECT and not view.folder_button.isEnabled()


def test_item_text_marks_reports_that_exist():
    item = ExplanationFileDTO("x.md", "Title", "r.tif", "2024-01-02T03:04:05", "C:/p/reports/x.pdf")
    assert item_text(item) == "Title\nr.tif  ·  2024-01-02 03:04  ·  PDF ready"
