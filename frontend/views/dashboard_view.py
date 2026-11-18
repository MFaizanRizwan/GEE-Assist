"""Dashboard shown right after signing in.

From the top: a greeting, the open project's name as a heading right under it, and at the bottom the three most recent projects
and the latest analysis results of those projects. The dashboard has no buttons: pages are
opened from the side bar, projects are created, opened, renamed, moved and closed from the
File menu, and clicking a recent project opens it.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO
from backend.dto.user_dto import UserDTO
from frontend import theme

TILE_WIDTH = 330
RECENT_PROJECTS = 3
RESULTS_PER_PROJECT = 3
_CATEGORY_LABELS = {"LULC": "Land cover", "LST": "Surface temperature"}

STYLESHEET = f"""
QFrame#DashboardPanel {{
    background: {theme.WHITE};
    border: 1px solid {theme.BORDER};
    border-radius: 16px;
}}
QLabel#SectionTitle {{ color: {theme.INK}; font-weight: 600; font-size: 10.5pt; }}
QLabel#Overline {{ color: {theme.MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#ProjectName {{ font-family: "{theme.SERIF}"; font-size: 18pt; color: {theme.INK}; }}
QLabel#ItemTitle {{ color: {theme.INK}; font-weight: 600; }}
QLabel#ItemPath, QLabel#ItemMeta {{ color: {theme.MUTED}; font-size: 8.5pt; }}
QFrame#RecentProject {{
    background: {theme.FOAM}; border: 1px solid {theme.BORDER}; border-radius: 8px;
}}
QFrame#RecentProject:hover {{ border-color: {theme.LEAF}; }}
QFrame#RecentProject[current="true"] {{ border-color: {theme.LEAF}; }}
QFrame#ResultRow {{ border: none; border-top: 1px solid {theme.BORDER}; border-radius: 0; background: transparent; }}
"""


def category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category.replace("_", " ").title() if category.islower() else category)


def format_when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return iso or ""


class ProjectHeading(QWidget):
    """Right under the welcome: the open project's name and folder, or a note on how to create or
    open one. Plain text, left-aligned, not a card."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ProjectHeading")
        self.pages = QStackedWidget()

        # ---- no project open
        empty = QWidget()
        self.empty_title = QLabel("No project open", objectName="ProjectName")
        self.empty_text = QLabel("Create one with File → New project… or open one with File → Open project… "
                                 "(or click a recent project). Datasets are downloaded into a project and "
                                 "its analysis results are kept in it.", objectName="Muted")
        self.empty_text.setWordWrap(True)
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(8)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_text)

        # ---- a project is open
        open_page = QWidget()
        self.name = QLabel(objectName="ProjectName")
        self.path = QLabel(objectName="ItemPath")
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path.setWordWrap(True)
        open_layout = QVBoxLayout(open_page)
        open_layout.setContentsMargins(0, 0, 0, 0)
        open_layout.setSpacing(4)
        open_layout.addWidget(QLabel("CURRENT PROJECT", objectName="Overline"))
        open_layout.addWidget(self.name)
        open_layout.addWidget(self.path)

        self.pages.addWidget(empty)
        self.pages.addWidget(open_page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)
        self.show_project(None)

    def show_project(self, project: ProjectDTO | None) -> None:
        if project is None:
            self.pages.setCurrentIndex(0)
            return
        self.name.setText(project.name)
        self.path.setText(project.folder)
        self.pages.setCurrentIndex(1)


class RecentProjectItem(QFrame):
    """A recent project, as in an editor's start page: its name and the folder it is in. Click to open."""

    clicked = pyqtSignal(str)  # the project folder

    def __init__(self, project: ProjectDTO, current: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.project = project
        self.setObjectName("RecentProject")
        self.setProperty("current", current)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Open {project.folder}" if not current else f"{project.folder} (open now)")
        title = QLabel(project.name + ("   · open" if current else ""), objectName="ItemTitle")
        path = QLabel(project.location, objectName="ItemPath")
        path.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        layout.addWidget(title)
        layout.addWidget(path)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.project.folder)
        super().mouseReleaseEvent(event)


class ResultRow(QFrame):
    """One analysis result: what ran, when, its first number, and whether its GeoTIFF was saved."""

    def __init__(self, record: AnalysisRecordDTO, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ResultRow")
        processes = ", ".join(record.processes[:3]) + ("…" if len(record.processes) > 3 else "")
        title = QLabel(f"{category_label(record.category)}" + (f" · {processes}" if processes else ""),
                       objectName="ItemTitle")
        details = [format_when(record.created_at)]
        if record.metrics:
            name, value = next(iter(record.metrics.items()))
            details.append(f"{name}: {value:.3g}")
        details.append("saved" if record.saved else "not saved")
        meta = QLabel("  ·  ".join(details), objectName="ItemMeta")
        meta.setWordWrap(True)
        self.setToolTip("\n".join(f"{k}: {v:.4g}" for k, v in record.metrics.items()) or "No numbers recorded")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(1)
        layout.addWidget(title)
        layout.addWidget(meta)


def _panel(title: str) -> tuple[QFrame, QVBoxLayout, QVBoxLayout]:
    """A titled panel; returns (panel, header row layout, body layout)."""
    panel = QFrame(objectName="DashboardPanel")
    panel.setFixedWidth(TILE_WIDTH)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    header = QHBoxLayout()
    header.addWidget(QLabel(title, objectName="SectionTitle"), 1)
    layout.addLayout(header)
    body = QVBoxLayout()
    body.setSpacing(8)
    layout.addLayout(body)
    layout.addStretch(1)
    return panel, header, body


def _clear(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)  # gone at once, not only when Qt gets round to deleting it
            widget.deleteLater()


class DashboardView(QWidget):
    """Start page after sign-in. Clicking a recent project emits ``open_recent``."""

    open_recent = pyqtSignal(str)  # a recent project's folder

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(STYLESHEET)
        self.recent_items: list[RecentProjectItem] = []
        self.result_rows: list[ResultRow] = []

        self.greeting = QLabel(objectName="Title")
        self.project_heading = ProjectHeading()

        # ---- bottom: recent projects | their latest analysis results
        recent_panel, _, self.recent_list = _panel("Recent projects")
        results_panel, _, self.results_list = _panel("Recent analysis results")
        bottom = QHBoxLayout()
        bottom.setSpacing(20)
        bottom.addWidget(recent_panel, 0, Qt.AlignmentFlag.AlignTop)
        bottom.addWidget(results_panel, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(6)
        column.addWidget(self.greeting)
        column.addSpacing(10)
        column.addWidget(self.project_heading)  # just after the welcome
        column.addSpacing(20)
        column.addLayout(bottom)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addLayout(column)
        row.addStretch(1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 28, 28, 28)
        content_layout.addStretch(1)
        content_layout.addLayout(row)
        content_layout.addStretch(2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

        self.set_projects(None, [], [])

    def set_user(self, user: UserDTO) -> None:
        first_name = (user.full_name or "").split(" ")[0] or "there"
        self.greeting.setText(f"Welcome, {first_name}")

    def set_projects(self, current: ProjectDTO | None, recent: list[ProjectDTO],
                     results: list[tuple[ProjectDTO, list[AnalysisRecordDTO]]]) -> None:
        """The open project, the user's recent projects and the latest analysis results of those."""
        self.project_heading.show_project(current)

        _clear(self.recent_list)
        self.recent_items = []
        for project in recent[:RECENT_PROJECTS]:
            item = RecentProjectItem(project, current is not None and project.id == current.id)
            item.clicked.connect(self.open_recent)
            self.recent_list.addWidget(item)
            self.recent_items.append(item)
        if not self.recent_items:
            self.recent_list.addWidget(self._empty("Projects you create or open appear here."))

        _clear(self.results_list)
        self.result_rows = []
        for project, records in results[:RECENT_PROJECTS]:
            if not records:
                continue
            self.results_list.addWidget(QLabel(project.name, objectName="Overline"))
            for record in records[:RESULTS_PER_PROJECT]:
                row = ResultRow(record)
                self.results_list.addWidget(row)
                self.result_rows.append(row)
        if not self.result_rows:
            self.results_list.addWidget(self._empty("Results of the analyses you run in your projects appear here."))

    @staticmethod
    def _empty(text: str) -> QLabel:
        label = QLabel(text, objectName="ItemMeta")
        label.setWordWrap(True)
        return label
