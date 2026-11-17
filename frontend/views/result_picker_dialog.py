"""Ask which saved analysis result (.tif) of the open project to explain with AI.

Opened from the side bar's "AI Explanation": the project may hold many results, so the
user picks one. Each row shows the analysis and its processes, the file and when it was made.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.dto.result_dto import ResultDTO
from frontend import theme

STYLESHEET = f"""
QDialog {{ background: {theme.WHITE}; }}
QLabel#PickerTitle {{ font-family: "{theme.SERIF}"; font-size: 16pt; color: {theme.INK}; }}
QListWidget {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 4px;
    color: {theme.TEXT};
}}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {theme.MINT}; color: {theme.INK}; }}
"""


def result_title(result: ResultDTO) -> str:
    """e.g. "Vegetation: NDVI, EVI"; "Analysis result" when the file does not say."""
    if result.category and result.processes:
        return f"{result.category}: {', '.join(result.processes)}"
    return result.category or "Analysis result"


def item_text(result: ResultDTO) -> str:
    """Two lines: what the result is, then its file and when it was made."""
    when = result.created_at.replace("T", " ")[:16]
    details = "  ·  ".join(part for part in (Path(result.output_path).name, when) if part)
    return f"{result_title(result)}\n{details}"


class ResultPickerDialog(QDialog):
    def __init__(self, results: list[ResultDTO], project_name: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("AI explanation")
        self.setModal(True)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(STYLESHEET)
        self.results = list(results)

        title = QLabel("Which result should be explained?", objectName="PickerTitle")
        where = f"the {project_name} project" if project_name else "this project"
        hint = QLabel(f"The analysis results saved in {where}, newest first. Gemini is sent the chosen "
                      "GeoTIFF with its metadata.", objectName="Muted")
        hint.setWordWrap(True)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        for result in self.results:
            item = QListWidgetItem(item_text(result))
            item.setToolTip(result.output_path)
            self.list.addItem(item)
        if self.results:
            self.list.setCurrentRow(0)

        self.explain_button = QPushButton("✦ Explain with AI", objectName="PrimaryButton")
        self.cancel_button = QPushButton("Cancel", objectName="SecondaryButton")
        for button in (self.explain_button, self.cancel_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.explain_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

        self.explain_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.list.itemDoubleClicked.connect(self._explain_item)
        self.list.currentRowChanged.connect(lambda _row: self._update())
        self._update()

    def chosen(self) -> ResultDTO | None:
        row = self.list.currentRow()
        return self.results[row] if 0 <= row < len(self.results) else None

    def accept(self) -> None:
        if self.chosen() is not None:
            super().accept()

    def _explain_item(self, item: QListWidgetItem) -> None:
        self.list.setCurrentItem(item)  # the row double-clicked, whatever was chosen before
        self.accept()

    def _update(self) -> None:
        self.explain_button.setEnabled(self.chosen() is not None)


def choose_result(results: list[ResultDTO], project_name: str = "", parent: QWidget | None = None) -> ResultDTO | None:
    """Ask which result to explain; None if cancelled."""
    dialog = ResultPickerDialog(results, project_name, parent)
    return dialog.chosen() if dialog.exec() == QDialog.DialogCode.Accepted else None
