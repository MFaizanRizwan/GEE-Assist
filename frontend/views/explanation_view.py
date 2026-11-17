"""AI explanation page (UC-08 Get AI Explanation).

Opened with "Explain with AI" on the Analysis page. The result's GeoTIFF is first saved in
the open project's analysis folder (if it was not saved yet), then its metadata is shown on
the left: which analysis ran and with which settings, the dataset **before** the analysis
(and any earlier dataset it was compared with) and the result **after** it, with its numbers.
Meanwhile the saved GeoTIFF, a preview of each layer and the prompt go to Gemini; its
explanation appears on the right and is kept next to the result as ``<result>_explanation.md``.
"""

from __future__ import annotations

import html
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO, RasterMetadataDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import GeeAssistError
from frontend import theme
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.raster_legend import format_value
from frontend.workers.task_worker import run_task

METADATA_WIDTH = 420

STYLESHEET = f"""
#ExplanationPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#ExplanationCard {{ background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}
QFrame#ExplanationCard QLabel {{ background: transparent; }}
QLabel#StepTitle {{ color: {theme.INK}; font-weight: 700; font-size: 10.5pt; }}
QTextBrowser {{ background: transparent; border: none; color: {theme.TEXT}; }}
"""

WAITING_TEXT = "Gemini's explanation appears here."


class ExplanationView(QWidget):
    back_requested = pyqtSignal()
    result_saved = pyqtSignal(object)        # ResultDTO: the result as saved in the project
    explanation_ready = pyqtSignal(object)   # ExplanationDTO

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ExplanationPage")
        self.setStyleSheet(STYLESHEET)
        self._facade = facade
        self.result: ResultDTO | None = None
        self.request: ExplanationRequestDTO | None = None
        self.explanation: ExplanationDTO | None = None
        self.busy = False
        self._run = 0                        # answers of an earlier run are ignored

        self.title = QLabel("AI explanation", objectName="PageTitle")
        self.subtitle = QLabel("Gemini explains an analysis result from its GeoTIFF and metadata.",
                               objectName="PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.back_button = QPushButton("← Back to analysis", objectName="SecondaryButton")
        self.banner = StatusBanner()
        self.progress = QProgressBar(objectName="BusyBar")
        self.progress.setRange(0, 0)  # busy, no percentage
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.hide()

        # ---- left: what was analysed, the metadata before and after
        self.metadata_view = QTextBrowser()
        self.metadata_view.setOpenLinks(False)
        metadata_card = QFrame(objectName="ExplanationCard")
        metadata_card.setFixedWidth(METADATA_WIDTH)
        left = QVBoxLayout(metadata_card)
        left.setContentsMargins(16, 14, 16, 14)
        left.addWidget(QLabel("What was sent to Gemini", objectName="StepTitle"))
        left.addWidget(self.metadata_view, 1)

        # ---- right: Gemini's explanation
        self.answer_view = QTextBrowser()
        self.answer_view.setOpenExternalLinks(True)
        self.answer_view.setPlaceholderText(WAITING_TEXT)
        self.sent_label = QLabel(objectName="Muted")
        self.sent_label.setWordWrap(True)
        self.again_button = QPushButton("Explain again", objectName="SecondaryButton")
        self.copy_button = QPushButton("Copy", objectName="SecondaryButton")
        self.folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        answer_card = QFrame(objectName="ExplanationCard")
        right = QVBoxLayout(answer_card)
        right.setContentsMargins(16, 14, 16, 14)
        right.addWidget(QLabel("Gemini's explanation", objectName="StepTitle"))
        right.addWidget(self.answer_view, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.sent_label, 1)
        for button in (self.again_button, self.copy_button, self.folder_button):
            buttons.addWidget(button)
        right.addLayout(buttons)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        header.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignTop)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(metadata_card)
        body.addWidget(answer_card, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.banner)
        layout.addWidget(self.progress)
        layout.addLayout(body, 1)

        for button in (self.back_button, self.again_button, self.copy_button, self.folder_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested)
        self.again_button.clicked.connect(self.explain_again)
        self.copy_button.clicked.connect(self.copy_explanation)
        self.folder_button.clicked.connect(self.open_folder)
        self._update_buttons()

    # ------------------------------------------------------------- explaining
    def explain(self, result: ResultDTO) -> None:
        """Save ``result`` in the project if needed, show its metadata and ask Gemini to explain it."""
        self._run += 1
        self.result, self.request, self.explanation = result, None, None
        self.subtitle.setText(f"{result.category}: {', '.join(result.processes)}  ·  {Path(result.output_path).name}")
        self.metadata_view.clear()
        self.answer_view.clear()
        self.sent_label.clear()
        self._set_busy(True)
        self.banner.show_info("Saving the result in the project and reading its metadata…")
        run_task(self, self._facade.prepare_explanation, result,
                 on_success=lambda request, run=self._run: self._on_prepared(run, request),
                 on_error=lambda exc, run=self._run: self._on_failed(run, exc))

    def explain_again(self) -> None:
        """Ask Gemini again for the same result (e.g. after an error, or for another wording)."""
        if self.request is None:
            if self.result is not None and not self.busy:
                self.explain(self.result)
            return
        if self.busy:
            return
        self._run += 1
        self._send(self.request)

    def _on_prepared(self, run: int, request: ExplanationRequestDTO) -> None:
        if run != self._run:
            return
        self.request, self.result = request, request.result
        self.subtitle.setText(f"{request.category_label or request.category}: {', '.join(request.result.processes)}"
                              f"  ·  {Path(request.tif_path).name}")
        self.metadata_view.setHtml(metadata_html(request))
        self.result_saved.emit(request.result)
        self._send(request)

    def _send(self, request: ExplanationRequestDTO) -> None:
        self._set_busy(True)
        previews = len(request.previews)
        self.banner.show_info(f"Sending {Path(request.tif_path).name}, {previews} layer preview"
                              f"{'s' if previews != 1 else ''} and the metadata to Gemini…")
        run_task(self, self._facade.explain_analysis_result, request,
                 on_success=lambda explanation, run=self._run: self._on_explained(run, explanation),
                 on_error=lambda exc, run=self._run: self._on_failed(run, exc))

    def _on_explained(self, run: int, explanation: ExplanationDTO) -> None:
        if run != self._run:
            return
        self.explanation = explanation
        self._set_busy(False)
        self.answer_view.setMarkdown(explanation.text)
        self.sent_label.setText(sent_text(explanation))
        if explanation.saved_path:
            self.banner.show_success(f"Explanation saved to {explanation.saved_path}")
        else:
            self.banner.show_info("The explanation could not be saved in the project; copy it to keep it.")
        self.explanation_ready.emit(explanation)

    def _on_failed(self, run: int, exc: Exception) -> None:
        if run != self._run:
            return
        self._set_busy(False)
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else
                               f"The explanation could not be made: {exc}")

    # ------------------------------------------------------------- actions
    def copy_explanation(self) -> None:
        if self.explanation is not None:
            QApplication.clipboard().setText(self.explanation.text)
            self.banner.show_success("Explanation copied.")

    def open_folder(self) -> None:
        if self.result is not None and self.result.saved:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.result.output_path).parent)))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.progress.setVisible(busy)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.again_button.setEnabled(not self.busy and self.result is not None)
        self.again_button.setText("Explain again" if self.explanation is not None else "Try again")
        self.copy_button.setEnabled(not self.busy and self.explanation is not None)
        self.folder_button.setEnabled(self.result is not None and self.result.saved)


# ----------------------------------------------------------------------------- text
def sent_text(explanation: ExplanationDTO) -> str:
    """What Gemini was given, e.g. "Sent to Gemini: result.tif (saved in the project), 2 layer previews and ..."."""
    request = explanation.request
    name = Path(request.tif_path).name if request else "the result"
    count = len(request.previews) if request else 0
    previews = f"{count} layer preview{'s' if count != 1 else ''} and the metadata"
    model = f"  ·  {explanation.model}" if explanation.model else ""
    if explanation.tif_attached:
        return f"Sent to Gemini: {name} (saved in the project), {previews}{model}"
    return f"Saved in the project: {name}. Gemini does not read GeoTIFFs, so it was sent {previews}{model}"


def metadata_html(request: ExplanationRequestDTO) -> str:
    """The analysis, the metadata before and after it, and its numbers, as small tables."""
    result = request.result
    parts = [_section("Analysis", [
        ("Analysis", request.category_label or request.category),
        ("Processes", ", ".join(p.key + (f" ({p.name})" if p.name else "") for p in request.processes)),
        *((("Parameters", ", ".join(f"{k} = {v}" for k, v in request.params.items())),) if request.params else ()),
        ("Ran on", " · ".join(x for x in (result.device, f"{result.seconds:.1f} s" if result.seconds else "",
                                            result.created_at) if x)),
    ])]
    parts.append(_metadata("Before the analysis: dataset", request.before))
    for index, other in enumerate(request.compared_with, start=1):
        parts.append(_metadata(f"Before the analysis: compared dataset {index}", other))
    parts.append(_metadata("After the analysis: result", request.after))
    if request.layers:
        parts.append(_section("Layers", [(layer.label + (f" ({layer.unit})" if layer.unit else ""), layer.legend or "—")
                                         for layer in request.layers]))
    if result.metrics:
        parts.append(_section("Numbers", [(name, format_value(value)) for name, value in result.metrics.items()]))
    return "".join(parts)


def _metadata(title: str, metadata: RasterMetadataDTO | None) -> str:
    return _section(title, metadata.rows() if metadata is not None else [("", "Not available")])


def _section(title: str, rows: list[tuple[str, str]]) -> str:
    cells = "".join(
        f"<tr><td style='color:{theme.MUTED}; padding:2px 10px 2px 0; white-space:nowrap'>{html.escape(label)}</td>"
        f"<td style='color:{theme.INK}; padding:2px 0'>{html.escape(str(value))}</td></tr>"
        for label, value in rows if value != "")
    return (f"<p style='margin:10px 0 4px 0; color:{theme.MUTED}; font-size:8.5pt; font-weight:600'>"
            f"{html.escape(title.upper())}</p><table cellspacing='0'>{cells}</table>")
