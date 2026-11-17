"""Reports page (UC-09 Generate Report): PDF reports made from saved AI explanations.

Lists the AI explanations kept in the open project's ``explanation`` folder, newest first.
"Create PDF report" makes the PDF of the chosen one (the pictures of its analysis result on
top, then the explanation) and keeps it in the project's ``reports`` folder; "Export PDF…"
saves a copy anywhere on the computer the user chooses.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.report_dto import ExplanationFileDTO, ReportDTO
from backend.exceptions import GeeAssistError
from frontend import theme
from frontend.project_paths import current_project
from frontend.report_pdf import render_report_pdf
from frontend.widgets.form_parts import StatusBanner
from frontend.workers.task_worker import run_task

STYLESHEET = f"""
#ReportsPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#ReportsCard {{ background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}
QFrame#ReportsCard QLabel {{ background: transparent; }}
QLabel#StepTitle {{ color: {theme.INK}; font-weight: 700; font-size: 10.5pt; }}
QListWidget {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 4px;
    color: {theme.TEXT};
}}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {theme.MINT}; color: {theme.INK}; }}
"""

NO_PROJECT = "Create or open a project: its AI explanations are listed here."
NO_EXPLANATIONS = ("No AI explanations in this project yet. Run an analysis, press “Explain with AI”, then "
                   "make its PDF report here.")


class ReportsView(QWidget):
    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ReportsPage")
        self.setStyleSheet(STYLESHEET)
        self._facade = facade
        self.explanations: list[ExplanationFileDTO] = []
        self.busy = False

        self.title = QLabel("Reports", objectName="PageTitle")
        self.subtitle = QLabel("Make a PDF report from an AI explanation: the picture of its analysis result "
                               "first, then the explanation. Reports are kept in the project's reports folder.",
                               objectName="PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.banner = StatusBanner()
        self.progress = QProgressBar(objectName="BusyBar")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.hide()

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.empty_label = QLabel(objectName="Muted")
        self.empty_label.setWordWrap(True)
        self.refresh_button = QPushButton("Refresh", objectName="SecondaryButton")
        self.create_button = QPushButton("Create PDF report", objectName="PrimaryButton")
        self.open_button = QPushButton("Open PDF", objectName="SecondaryButton")
        self.export_button = QPushButton("Export PDF…", objectName="SecondaryButton")
        self.export_button.setToolTip("Save a copy of the report anywhere on this computer")
        self.folder_button = QPushButton("Open reports folder", objectName="SecondaryButton")

        card = QFrame(objectName="ReportsCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(8)
        inner.addWidget(QLabel("AI explanations in this project", objectName="StepTitle"))
        inner.addWidget(self.empty_label)
        inner.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch(1)
        for button in (self.open_button, self.export_button, self.create_button):
            buttons.addWidget(button)
        inner.addLayout(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.banner)
        layout.addWidget(self.progress)
        layout.addWidget(card, 1)

        for button in (self.refresh_button, self.create_button, self.open_button, self.export_button,
                       self.folder_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(lambda: self.refresh())
        self.create_button.clicked.connect(lambda: self.create_report())
        self.open_button.clicked.connect(self.open_pdf)
        self.export_button.clicked.connect(self.export_pdf)
        self.folder_button.clicked.connect(self.open_reports_folder)
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())
        self.list.itemDoubleClicked.connect(lambda _item: self.open_pdf() if self._report_of_current()
                                            else self.create_report())
        self._update_buttons()

    # ------------------------------------------------------------- listing
    def refresh(self, select: str = "") -> None:
        """List the open project's explanations again, keeping (or moving to) ``select``."""
        keep = select or (self.current().path if self.current() else "")
        has_project = current_project(self._facade) is not None
        try:
            self.explanations = list(self._facade.list_explanations()) if has_project else []
        except GeeAssistError as exc:
            self.explanations = []
            self.banner.show_error(str(exc))
        self.list.blockSignals(True)
        self.list.clear()
        for explanation in self.explanations:
            item = QListWidgetItem(item_text(explanation))
            item.setToolTip(explanation.report_path or explanation.path)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.empty_label.setText("" if self.explanations else (NO_EXPLANATIONS if has_project else NO_PROJECT))
        self.empty_label.setVisible(not self.explanations)
        paths = [explanation.path for explanation in self.explanations]
        if keep in paths:
            self.list.setCurrentRow(paths.index(keep))
        elif paths:
            self.list.setCurrentRow(0)
        self._update_buttons()

    def current(self) -> ExplanationFileDTO | None:
        row = self.list.currentRow()
        return self.explanations[row] if 0 <= row < len(self.explanations) else None

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self.busy:
            self.refresh()

    # ------------------------------------------------------------- creating
    def create_report(self, explanation_path: str = "") -> None:
        """Make (or make again) the PDF report of an explanation and keep it in the project."""
        path = explanation_path or (self.current().path if self.current() else "")
        if not path or self.busy:
            return
        if explanation_path:
            self.refresh(select=explanation_path)
        self._set_busy(True)
        self.banner.show_info(f"Creating the PDF report of {Path(path).name}…")
        run_task(self, self._facade.build_report, path, on_success=self._on_built, on_error=self._on_failed)

    def _on_built(self, report: ReportDTO) -> None:
        try:
            pdf = render_report_pdf(report)  # Qt draws on this (the UI) thread
        except Exception as exc:  # noqa: BLE001 - shown to the user, never lost
            self._on_failed(exc)
            return
        run_task(self, self._facade.save_report, report, pdf,
                 on_success=lambda path, note=report.note: self._on_saved(report.explanation_path, path, note),
                 on_error=self._on_failed)

    def _on_saved(self, explanation_path: str, pdf_path: str, note: str) -> None:
        self._set_busy(False)
        self.refresh(select=explanation_path)
        self.banner.show_success(f"Report saved to {pdf_path}" + (f". {note}" if note else ""))

    def _on_failed(self, exc: Exception) -> None:
        self._set_busy(False)
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else
                               f"The report could not be created: {exc}")

    # ------------------------------------------------------------- the PDF
    def open_pdf(self) -> None:
        report = self._report_of_current()
        if report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(report))

    def export_pdf(self) -> None:
        """Save a copy of the report wherever the user chooses (e.g. Documents, a USB drive)."""
        report = self._report_of_current()
        if not report:
            return
        destination = self.choose_export_path(str(Path.home() / "Documents" / Path(report).name))
        if not destination:
            return
        try:
            exported = self._facade.export_report(report, destination)
        except GeeAssistError as exc:
            self.banner.show_error(str(exc))
            return
        self.banner.show_success(f"Report exported to {exported}")

    def choose_export_path(self, suggested: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF report", suggested, "PDF (*.pdf)")
        return path

    def open_reports_folder(self) -> None:
        project = current_project(self._facade)
        if project is not None:
            Path(project.reports_dir).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(project.reports_dir))

    def _report_of_current(self) -> str:
        current = self.current()
        return current.report_path if current and current.report_path and Path(current.report_path).is_file() else ""

    # ------------------------------------------------------------- state
    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.progress.setVisible(busy)
        self._update_buttons()

    def _update_buttons(self) -> None:
        current, has_pdf = self.current(), bool(self._report_of_current())
        self.create_button.setEnabled(current is not None and not self.busy)
        self.create_button.setText("Create PDF again" if has_pdf else "Create PDF report")
        self.open_button.setEnabled(has_pdf and not self.busy)
        self.export_button.setEnabled(has_pdf and not self.busy)
        self.folder_button.setEnabled(current_project(self._facade) is not None)


def item_text(explanation: ExplanationFileDTO) -> str:
    """Two lines: the explanation's title, then its result, when it was made and whether its PDF exists."""
    when = explanation.explained_at.replace("T", " ")[:16]
    details = "  ·  ".join(part for part in (explanation.result_name, when,
                                              "PDF ready" if explanation.report_path else "") if part)
    return f"{explanation.title}\n{details}"
