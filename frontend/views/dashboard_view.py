"""Dashboard shown right after signing in.

From the top: a greeting, the open project (or buttons to create / open one), one card per
workspace, and at the bottom the three most recent projects and the latest analysis results
of those projects.

"Query Input", "Download" and "Analysis" open their pages; "Reports" is a placeholder
for a use case that is not built yet.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO
from backend.dto.user_dto import UserDTO
from frontend import theme
from frontend.widgets.form_widgets import add_soft_shadow

TILE_WIDTH = 330
RECENT_PROJECTS = 3
RESULTS_PER_PROJECT = 3
_CATEGORY_LABELS = {"LULC": "Land cover", "LST": "Surface temperature"}

STYLESHEET = f"""
QFrame#DashboardTile, QFrame#ProjectCard, QFrame#DashboardPanel {{
    background: {theme.WHITE};
    border: 1px solid {theme.BORDER};
    border-radius: 16px;
}}
QFrame#DashboardTile[enabled="false"] {{ background: {theme.TILE_DISABLED_BG}; }}
QLabel#TileBadge {{
    color: {theme.WHITE};
    font-size: 16pt;
    border-radius: 22px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {theme.LEAF}, stop:1 {theme.OCEAN});
}}
QLabel#TileBadge:disabled {{ background: {theme.MINT}; color: {theme.SUBTLE}; }}
QLabel#TileTitle {{ font-family: "{theme.SERIF}"; font-size: 14pt; color: {theme.INK}; }}
QLabel#TileTitle:disabled {{ color: {theme.MUTED}; }}
QLabel#ComingSoon {{
    color: {theme.MUTED}; background: {theme.FOAM}; border: 1px solid {theme.BORDER};
    border-radius: 9px; padding: 2px 9px; font-size: 8.5pt;
}}
QLabel#SectionTitle {{ color: {theme.INK}; font-weight: 600; font-size: 10.5pt; }}
QLabel#Overline {{ color: {theme.MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#ProjectName {{ font-family: "{theme.SERIF}"; font-size: 15pt; color: {theme.INK}; }}
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


class DashboardTile(QFrame):
    """One workspace card: badge, title, short description and an action button."""

    def __init__(self, glyph: str, title: str, text: str, action: str | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DashboardTile")
        self.setFixedWidth(TILE_WIDTH)
        add_soft_shadow(self)

        badge = QLabel(glyph, objectName="TileBadge")
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label = QLabel(title, objectName="TileTitle")
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(badge)
        head.addWidget(title_label, 1)

        description = QLabel(text, objectName="Muted")
        description.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addLayout(head)
        layout.addWidget(description)
        layout.addStretch(1)

        self.button: QPushButton | None = None
        if action:
            self.button = QPushButton(action, objectName="PrimaryButton")
            self.button.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            self.setEnabled(False)
            layout.addWidget(QLabel("Coming soon", objectName="ComingSoon"), 0, Qt.AlignmentFlag.AlignLeft)


def _button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text, objectName="PrimaryButton" if primary else "SecondaryButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet("QPushButton { padding: 7px 14px; font-size: 9.5pt; }")
    return button


class ProjectCard(QFrame):
    """The open project with its actions, or buttons to create / open one."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ProjectCard")
        self.setFixedWidth(2 * TILE_WIDTH + 20)  # as wide as the two columns of cards below
        add_soft_shadow(self, blur=32, alpha=24, y_offset=8)
        self.pages = QStackedWidget()

        # ---- no project open
        empty = QWidget()
        self.empty_title = QLabel("No project open", objectName="ProjectName")
        empty_text = QLabel("Create a project to start working: datasets are downloaded into its downloads "
                            "folder and analysis results are kept in its analysis folder.", objectName="Muted")
        empty_text.setWordWrap(True)
        self.new_button = _button("New project", primary=True)
        self.open_button = _button("Open project…")
        empty_actions = QHBoxLayout()
        empty_actions.setSpacing(8)
        empty_actions.addWidget(self.new_button)
        empty_actions.addWidget(self.open_button)
        empty_actions.addStretch(1)
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(8)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(empty_text)
        empty_layout.addLayout(empty_actions)

        # ---- a project is open
        open_page = QWidget()
        self.name = QLabel(objectName="ProjectName")
        self.path = QLabel(objectName="ItemPath")
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path.setWordWrap(True)
        self.folder_button = _button("Open folder")
        self.rename_button = _button("Rename…")
        self.move_button = _button("Move…")
        self.close_button = _button("Close")
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for button in (self.folder_button, self.rename_button, self.move_button, self.close_button):
            actions.addWidget(button)
        actions.addStretch(1)
        open_layout = QVBoxLayout(open_page)
        open_layout.setContentsMargins(0, 0, 0, 0)
        open_layout.setSpacing(4)
        open_layout.addWidget(QLabel("CURRENT PROJECT", objectName="Overline"))
        open_layout.addWidget(self.name)
        open_layout.addWidget(self.path)
        open_layout.addSpacing(8)
        open_layout.addLayout(actions)

        self.pages.addWidget(empty)
        self.pages.addWidget(open_page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
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
    """Start page after sign-in. Emits a signal for each card and project action."""

    open_query_input = pyqtSignal()
    open_downloads = pyqtSignal()
    open_analysis = pyqtSignal()
    new_project = pyqtSignal()
    open_project = pyqtSignal()
    open_recent = pyqtSignal(str)  # a recent project's folder
    rename_project = pyqtSignal()
    move_project = pyqtSignal()
    show_project_folder = pyqtSignal()
    close_project = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(STYLESHEET)
        self.recent_items: list[RecentProjectItem] = []
        self.result_rows: list[ResultRow] = []

        self.greeting = QLabel(objectName="Title")
        subtitle = QLabel("Choose what you want to work on.", objectName="Subtitle")
        self.project_card = ProjectCard()

        self.query_tile = DashboardTile(
            "✦", "Query Input",
            "Describe a request in plain language or fill the parameter form: dataset, "
            "area of interest, dates and analysis.",
            "Open Query Input",
        )
        self.download_tile = DashboardTile(
            "⤓", "Download",
            "Fetch requested imagery from Google Earth Engine in chunks; pause, resume or cancel any time.",
            "Open Downloads",
        )
        self.analysis_tile = DashboardTile(
            "◔", "Analysis",
            "Run water, vegetation, land-cover and surface-temperature analyses on your downloads, on the GPU "
            "when there is one.",
            "Open Analysis",
        )
        tiles = (
            self.query_tile,
            self.download_tile,
            self.analysis_tile,
            DashboardTile("☰", "Reports", "Collect maps, charts and explanations into a report.", None),
        )
        grid = QGridLayout()
        grid.setSpacing(20)
        for i, tile in enumerate(tiles):
            grid.addWidget(tile, i // 2, i % 2)

        # ---- bottom: recent projects | their latest analysis results
        recent_panel, recent_header, self.recent_list = _panel("Recent projects")
        self.recent_new = _button("New")
        self.recent_open = _button("Open…")
        recent_header.addWidget(self.recent_new)
        recent_header.addWidget(self.recent_open)
        results_panel, _, self.results_list = _panel("Recent analysis results")
        bottom = QHBoxLayout()
        bottom.setSpacing(20)
        bottom.addWidget(recent_panel, 0, Qt.AlignmentFlag.AlignTop)
        bottom.addWidget(results_panel, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(6)
        column.addWidget(self.greeting)
        column.addWidget(subtitle)
        column.addSpacing(16)
        column.addWidget(self.project_card)
        column.addSpacing(20)
        column.addLayout(grid)
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

        assert self.query_tile.button is not None
        self.query_tile.button.clicked.connect(self.open_query_input)
        assert self.download_tile.button is not None
        self.download_tile.button.clicked.connect(self.open_downloads)
        assert self.analysis_tile.button is not None
        self.analysis_tile.button.clicked.connect(self.open_analysis)
        card = self.project_card
        for button, signal in ((card.new_button, self.new_project), (card.open_button, self.open_project),
                               (self.recent_new, self.new_project), (self.recent_open, self.open_project),
                               (card.rename_button, self.rename_project), (card.move_button, self.move_project),
                               (card.folder_button, self.show_project_folder),
                               (card.close_button, self.close_project)):
            button.clicked.connect(signal)
        self.set_projects(None, [], [])

    def set_user(self, user: UserDTO) -> None:
        first_name = (user.full_name or "").split(" ")[0] or "there"
        self.greeting.setText(f"Welcome, {first_name}")

    def set_projects(self, current: ProjectDTO | None, recent: list[ProjectDTO],
                     results: list[tuple[ProjectDTO, list[AnalysisRecordDTO]]]) -> None:
        """The open project, the user's recent projects and the latest analysis results of those."""
        self.project_card.show_project(current)

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
