"""Dashboard shown right after signing in.

On the left, from the top: a greeting, the open project's name as a heading right under it,
and that project's latest analysis results. On the right edge of the page: the three most recent
projects. Everything starts at the top left; all text is left-aligned. The dashboard has no buttons: pages are
opened from the side bar, projects are created, opened, renamed, moved and closed from the
File menu, and clicking a recent project opens it.
"""

from __future__ import annotations

import re
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
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

RECENT_PANEL_WIDTH = 300                        # the recent projects, on the right edge
RECENT_PROJECTS = 3
RESULTS_SHOWN = 3                               # the open project's latest results; "See more" lists them all
METRICS_SHOWN = 3                               # numbers shown in a result row; all of them in its tooltip
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
QLabel#ItemText {{ color: {theme.TEXT}; font-size: 9pt; }}
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
    """One analysis result, in three left-aligned columns:

    * what ran: the analysis and its processes; when, and whether its GeoTIFF was saved; where it
      ran and how long it took;
    * the dataset: its satellite and dates, then its place (read from the download's name);
    * its numbers: the first few; all of them in the row's tooltip.
    """

    def __init__(self, record: AnalysisRecordDTO, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ResultRow")
        processes = ", ".join(record.processes[:3]) + ("…" if len(record.processes) > 3 else "")
        what = [QLabel(f"{category_label(record.category)}" + (f" · {processes}" if processes else ""),
                       objectName="ItemTitle"),
                _meta("  ·  ".join(part for part in (format_when(record.created_at),
                                                     "saved" if record.saved else "not saved") if part))]
        run = run_summary(record)
        if run:
            what.append(_meta(run))

        satellite_and_dates, place = dataset_summary(record.dataset)
        dataset = [QLabel(satellite_and_dates or "Dataset not recorded", objectName="ItemText")]
        if place:
            dataset.append(_meta(place))

        numbers = [QLabel(f"{name}: {format_number(value)}", objectName="ItemText")
                   for name, value in list(record.metrics.items())[:METRICS_SHOWN]]
        if len(record.metrics) > METRICS_SHOWN:
            numbers.append(_meta(f"+{len(record.metrics) - METRICS_SHOWN} more (point at the row)"))
        if not numbers:
            numbers = [_meta("No numbers recorded")]
        self.setToolTip("\n".join(f"{k}: {format_number(v)}" for k, v in record.metrics.items())
                        or "No numbers recorded")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(18)
        for labels, stretch in ((what, 4), (dataset, 4), (numbers, 3)):
            column = QVBoxLayout()
            column.setSpacing(1)
            for label in labels:
                label.setWordWrap(True)
                column.addWidget(label)
            column.addStretch(1)
            layout.addLayout(column, stretch)
        self.labels = what + dataset + numbers


def _meta(text: str) -> QLabel:
    return QLabel(text, objectName="ItemMeta")


def run_summary(record: AnalysisRecordDTO) -> str:
    """Where and how fast it ran, e.g. "Ran on the CPU in 2.5 s"; "" when neither was recorded."""
    parts = []
    if record.device.strip():
        parts.append(f"on the {record.device.strip()}")
    if record.seconds:
        parts.append(f"in {record.seconds:.1f} s")
    return "Ran " + " ".join(parts) if parts else ""


# A download's name: <satellite>_<lon>_<lat>_<start date>_<end date> (see the download naming).
_DATASET_NAME = re.compile(r"^(?P<satellite>.+?)_(?P<lon>-?\d+(?:\.\d+)?)_(?P<lat>-?\d+(?:\.\d+)?)_"
                           r"(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})")


def dataset_summary(path: str) -> tuple[str, str]:
    """(satellite and dates, place) of the dataset analysed, read from its download name; the file
    name alone, and no place, when it is not a download's name; ("", "") when none was recorded."""
    if not path:
        return "", ""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    match = _DATASET_NAME.match(stem)
    if not match:
        return stem, ""
    lat, lon = float(match["lat"]), float(match["lon"])
    place = f"{abs(lat):.4f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.4f}° {'E' if lon >= 0 else 'W'}"
    return f"{match['satellite']}  ·  {format_date_range(match['start'], match['end'])}", place


def format_date_range(start: str, end: str) -> str:
    """e.g. "17 Aug – 17 Nov 2026" (the year once when both dates are in it)."""
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError:
        return f"{start} – {end}"
    left = first.strftime("%d %b") if first.year == last.year else first.strftime("%d %b %Y")
    return f"{left} – {last.strftime('%d %b %Y')}"


def format_number(value: float) -> str:
    """A result as briefly as it reads well (e.g. -0.428, 3.1, 1,530)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,.0f}" if abs(number) >= 1000 else f"{number:.3g}"


class AnalysisResultsDialog(QDialog):
    """A modal listing every analysis result of a project, newest first, in the same rows as the
    dashboard (which shows only the latest few); it scrolls when they do not fit."""

    def __init__(self, project_name: str, records: list[AnalysisRecordDTO], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Analysis results — {project_name}")
        self.setModal(True)
        self.setMinimumSize(760, 460)
        self.setStyleSheet(STYLESHEET + f"QDialog {{ background: {theme.WHITE}; }}")
        self.rows: list[ResultRow] = []

        title = QLabel(f"Analysis results of {project_name}", objectName="ProjectName")
        count = len(records)
        summary = QLabel(f"{count} result{'s' if count != 1 else ''}, newest first. Point at a row to see all "
                         "its numbers.", objectName="ItemMeta")
        rows = QWidget()
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(0, 0, 8, 0)
        rows_layout.setSpacing(0)
        for record in records:
            row = ResultRow(record)
            rows_layout.addWidget(row)
            self.rows.append(row)
        rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(rows)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        close = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        close.setObjectName("SecondaryButton")  # styled as the app's other buttons, not flat text
        close.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(summary)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.buttons)


def _panel(title: str, width: int | None = None) -> tuple[QFrame, QVBoxLayout, QVBoxLayout]:
    """A titled panel, ``width`` wide or as wide as its column; returns (panel, header row layout, body layout)."""
    panel = QFrame(objectName="DashboardPanel")
    if width is not None:
        panel.setFixedWidth(width)
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

        results_panel, _, self.results_list = _panel("Recent analysis results")  # of the open project
        self.results_panel = results_panel
        self.see_more = QPushButton("See more", objectName="SecondaryButton")
        self.see_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.see_more.clicked.connect(self.show_all_results)
        results_panel.layout().addWidget(self.see_more, 0, Qt.AlignmentFlag.AlignLeft)  # under the latest ones
        self._current: ProjectDTO | None = None
        self._results: list[AnalysisRecordDTO] = []
        self.recent_panel, _, self.recent_list = _panel("Recent projects", RECENT_PANEL_WIDTH)

        # ---- left: the welcome, the open project, its results
        column = QVBoxLayout()
        column.setSpacing(6)
        column.addWidget(self.greeting)
        column.addSpacing(10)
        column.addWidget(self.project_heading)  # just after the welcome
        column.addSpacing(20)
        column.addWidget(results_panel)
        column.addStretch(1)

        # ---- the two columns: the left one takes the room, the recent projects keep to the right edge
        row = QHBoxLayout()
        row.setSpacing(28)
        row.addLayout(column, 1)
        row.addWidget(self.recent_panel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 32, 36, 32)
        content_layout.addLayout(row)
        content_layout.addStretch(1)  # from the top, not centred
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
                     results: list[AnalysisRecordDTO]) -> None:
        """The open project with its latest analysis ``results`` (newest first), and the user's recent projects."""
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
        self._current, self._results = current, (list(results) if current is not None else [])
        for record in self._results[:RESULTS_SHOWN]:
            row = ResultRow(record)
            self.results_list.addWidget(row)
            self.result_rows.append(row)
        if not self.result_rows:
            self.results_list.addWidget(self._empty(
                f"Results of the analyses you run in {current.name} appear here." if current is not None
                else "Open a project to see its analysis results here."))
        hidden = len(self._results) - len(self.result_rows)
        self.see_more.setVisible(hidden > 0)
        if hidden > 0:
            self.see_more.setText(f"See more ({hidden} more)")
            self.see_more.setToolTip(f"All {len(self._results)} analysis results of {current.name}")

    def make_results_dialog(self) -> AnalysisResultsDialog:
        """The modal with every analysis result of the open project."""
        name = self._current.name if self._current is not None else ""
        return AnalysisResultsDialog(name, self._results, self)

    def show_all_results(self) -> None:
        """See more: every analysis result of the open project, in a modal."""
        if self._current is not None and self._results:
            self.make_results_dialog().exec()

    @staticmethod
    def _empty(text: str) -> QLabel:
        label = QLabel(text, objectName="ItemMeta")
        label.setWordWrap(True)
        return label
