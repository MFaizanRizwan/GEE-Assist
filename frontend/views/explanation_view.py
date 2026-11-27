"""AI explanation page (UC-08 Get AI Explanation).

Opened with "Explain with AI" on the Analysis page. The result's GeoTIFF is first saved in
the open project's analysis folder (if it was not saved yet), then its metadata is shown on
the left: which analysis ran and with which settings, the dataset **before** the analysis
(and any earlier dataset it was compared with) and the result **after** it, with its numbers.
Meanwhile the saved GeoTIFF, a preview of each layer and the prompt go to Gemini; its
explanation appears on the right and is kept in the project's ``explanation`` folder as
``<result>_explanation.md``; "PDF report" turns it into a PDF on the Reports page.
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
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO, RasterMetadataDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import GeeAssistError
from frontend import layout_mode, palette, theme, theming
from frontend.widgets.earth_loader import EarthLoader
from frontend.widgets.layer_meaning import meaning
from frontend.widgets.layer_values import layer_value
from frontend.widgets.map_area import MapArea
from frontend.widgets.raster_canvas import rgba_to_image
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.raster_legend import format_value
from frontend.workers.task_worker import run_task

MAP_SIZE = 1024             # longest side of the result map drawn beside the words
METADATA_HEIGHT = 220      # the folded-open 'what was sent' panel

def _stylesheet():
    return f"""
#ExplanationPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20.6pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#ExplanationCard {{ background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}
QFrame#ExplanationCard QLabel {{ background: transparent; }}
QLabel#StepTitle {{ color: {theme.INK}; font-weight: 700; font-size: 10pt; }}
QTextBrowser {{ background: transparent; border: none; color: {theme.TEXT}; }}
QTextBrowser#MetadataView {{ background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; }}
QPushButton#FoldButton {{
    background: transparent; border: none; color: {theme.OCEAN}; font-weight: 600; padding: 4px 0; text-align: left;
}}
QPushButton#FoldButton:hover {{ color: {theme.OCEAN_DARK}; text-decoration: underline; }}
"""

WAITING_TEXT = "Gemini's explanation appears here."


class ExplanationView(QWidget):
    back_requested = pyqtSignal()
    result_saved = pyqtSignal(object)        # ResultDTO: the result as saved in the project
    explanation_ready = pyqtSignal(object)   # ExplanationDTO
    report_requested = pyqtSignal(str)       # the saved explanation (.md) to make a PDF report of

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ExplanationPage")
        theming.styled(self, _stylesheet)
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

        # ---- left: the analysed result's map, so every claim can be checked against the picture
        self.map_area = MapArea(dark=layout_mode.is_modern() or palette.IS_DARK)
        self.map_area.setMinimumHeight(260)
        self.map_note = QLabel("The result's map appears here.", objectName="Muted")
        self.map_note.setWordWrap(True)
        map_card = QFrame(objectName="ExplanationCard")
        left = QVBoxLayout(map_card)
        left.setContentsMargins(16, 14, 16, 14)
        left.setSpacing(8)
        left.addWidget(QLabel("The result", objectName="StepTitle"))
        left.addWidget(self.map_area, 1)
        left.addWidget(self.map_note)

        # ---- right: Gemini's explanation, with what was sent to Gemini folded beneath it
        self.answer_view = QTextBrowser()
        self.answer_view.setOpenExternalLinks(True)
        self.answer_view.setPlaceholderText(WAITING_TEXT)
        self.metadata_view = QTextBrowser(objectName="MetadataView")
        self.metadata_view.setOpenLinks(False)
        self.metadata_view.setFixedHeight(METADATA_HEIGHT)
        self.metadata_view.hide()  # folded: the words and the map lead
        self.fold_button = QPushButton("Show what was sent to Gemini", objectName="FoldButton")
        self.fold_button.setCheckable(True)
        self.fold_button.toggled.connect(self._fold_metadata)
        self.sent_label = QLabel(objectName="Muted")
        self.sent_label.setWordWrap(True)
        self.again_button = QPushButton("Explain again", objectName="SecondaryButton")
        self.copy_button = QPushButton("Copy", objectName="SecondaryButton")
        self.folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        self.report_button = QPushButton("PDF report", objectName="PrimaryButton")
        self.report_button.setToolTip("Make a PDF of this explanation, with the analysis picture on top, "
                                      "and export it if you like")
        # While Gemini works, a rotating Earth replaces the answer area.
        self.answer_loader = EarthLoader(
            "Explaining the result…", "Gemini is reading the GeoTIFF and its metadata.", size=120
        )
        self.answer_stack = QStackedWidget()
        self.answer_stack.addWidget(self.answer_view)      # 0: the explanation
        self.answer_stack.addWidget(self.answer_loader)    # 1: the loader

        answer_card = QFrame(objectName="ExplanationCard")
        right = QVBoxLayout(answer_card)
        right.setContentsMargins(20, 14, 20, 14)
        right.setSpacing(8)
        right.addWidget(QLabel("Gemini's explanation", objectName="StepTitle"))
        right.addWidget(self.answer_stack, 1)
        right.addWidget(self.fold_button, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.metadata_view)
        right.addWidget(self.sent_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for button in (self.again_button, self.copy_button, self.folder_button, self.report_button):
            buttons.addWidget(button)
        right.addLayout(buttons)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        header.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignTop)
        body = QHBoxLayout()  # the map beside the words, each taking half
        body.setSpacing(14)
        body.addWidget(map_card, 1)
        body.addWidget(answer_card, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.banner)
        layout.addLayout(body, 1)

        for button in (self.back_button, self.again_button, self.copy_button, self.folder_button,
                       self.report_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested)
        self.again_button.clicked.connect(self.explain_again)
        self.copy_button.clicked.connect(self.copy_explanation)
        self.folder_button.clicked.connect(self.open_folder)
        self.report_button.clicked.connect(self.request_report)
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
        self._show_map(result)
        self._set_busy(True)
        self.banner.clear()
        run_task(self, self._facade.prepare_explanation, result,
                 on_success=lambda request, run=self._run: self._on_prepared(run, request),
                 on_error=lambda exc, run=self._run: self._on_failed(run, exc))

    def _show_map(self, result: ResultDTO) -> None:
        """Draw the result's first layer beside the words, in the background."""
        self.map_area.clear()
        self.map_note.setText("Drawing the result's map…")
        run_task(self, self._facade.get_map_layers, result, MAP_SIZE,
                 on_success=lambda layers, run=self._run: self._on_map(run, layers),
                 on_error=lambda _exc, run=self._run: self._on_map(run, []))

    def _on_map(self, run: int, layers) -> None:
        if run != self._run:
            return  # an earlier explanation's map
        try:
            layer = list(layers)[0]
            self.map_area.set_image(rgba_to_image(layer.data), layer.bounds, layer.width)
            self.map_area.set_value_probe(lambda x, y, layer=layer: layer_value(layer, x, y))
            legend = layer.legend
            if legend.kind == "scale":
                self.map_area.show_legend_scale(layer.name, tuple(legend.colours), legend.low, legend.high,
                                                meaning(layer.id, layer.style))
            elif legend.kind == "classes":
                self.map_area.show_legend_classes(legend.title or layer.name,
                                                  list(zip(legend.labels, legend.colours)))
            self.map_note.setText(f"{layer.name}: the picture Gemini was given, with its legend and scale.")
        except (IndexError, TypeError, ValueError, AttributeError):
            self.map_note.setText("The result's map could not be drawn; the explanation is unaffected.")

    def _fold_metadata(self, shown: bool) -> None:
        self.metadata_view.setVisible(shown)
        self.fold_button.setText("Hide what was sent to Gemini" if shown else "Show what was sent to Gemini")

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
        self.banner.clear()
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
            self.banner.show_error("The explanation could not be saved in the project; copy it to keep it.")
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

    def request_report(self) -> None:
        """Ask for the PDF report of the explanation shown (once it is saved in the project)."""
        if self.explanation is not None and self.explanation.saved_path:
            self.report_requested.emit(self.explanation.saved_path)

    def open_folder(self) -> None:
        """The project's explanation folder once the explanation is saved, else the result's folder."""
        if self.explanation is not None and self.explanation.saved_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.explanation.saved_path).parent)))
        elif self.result is not None and self.result.saved:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.result.output_path).parent)))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.answer_stack.setCurrentWidget(self.answer_loader if busy else self.answer_view)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.again_button.setEnabled(not self.busy and self.result is not None)
        self.again_button.setText("Explain again" if self.explanation is not None else "Try again")
        self.copy_button.setEnabled(not self.busy and self.explanation is not None)
        self.folder_button.setEnabled(self.result is not None and self.result.saved)
        self.report_button.setEnabled(not self.busy and self.explanation is not None
                                      and bool(self.explanation.saved_path))


# ----------------------------------------------------------------------------- text
def sent_text(explanation: ExplanationDTO) -> str:
    """What Gemini was given, e.g. "Sent to Gemini: result.tif (saved in the project), 2 layer previews and ..."."""
    request = explanation.request
    name = Path(request.tif_path).name if request else "the result"
    count = len(request.previews) if request else 0
    previews = (f"{count} layer preview{'s' if count != 1 else ''} and the metadata"
                if explanation.previews_attached and count else "the metadata only")
    model = f"  ·  {explanation.model}" if explanation.model else ""
    if explanation.tif_attached:
        return f"Sent to Gemini: {name} (saved in the project), {previews}{model}"
    return f"Saved in the project: {name}. Gemini refused the GeoTIFF, so it was sent {previews}{model}"


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
    return (f"<p style='margin:10px 0 4px 0; color:{theme.MUTED}; font-size:8pt; font-weight:600'>"
            f"{html.escape(title.upper())}</p><table cellspacing='0'>{cells}</table>")
