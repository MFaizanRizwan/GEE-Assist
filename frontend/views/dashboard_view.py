"""Dashboard shown right after signing in.

On the left, from the top: a greeting, the open project's name as a heading right under it,
and that project's latest analysis results. On the right edge of the page: the three most recent
projects. Everything starts at the top left; all text is left-aligned. "Create project" and
"Open project" buttons sit at the top left (the same actions are also in the File menu, and
clicking a recent project opens it); other pages are opened from the side bar.
"""

from __future__ import annotations

import re
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent
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
from backend.business.facade import IBusinessFacade
from frontend import theme
from frontend.widgets.project_charts import CategoryBarChart, MetricTrendChart
from frontend.widgets.raster_canvas import rgba_to_image
from frontend.widgets.result_gallery import ResultGallery
from frontend.workers.task_worker import run_task

RECENT_PANEL_WIDTH = 300                        # the recent projects, on the right edge
RECENT_PROJECTS = 3
RESULTS_SHOWN = 3                               # the open project's latest results; "See more" lists them all
METRICS_SHOWN = 3                               # numbers shown in a result row; all of them in its tooltip
MAPS_SHOWN = 6                                  # the open project's newest result maps, further down
MAP_PICTURE_SIZE = 480                          # longer side the maps are drawn at (then fitted in their tile)
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
QFrame#GlanceTile {{ background: {theme.FOAM}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}
QLabel#GlanceValue {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#ItemPath, QLabel#ItemMeta {{ color: {theme.MUTED}; font-size: 8.5pt; }}
QFrame#RecentProject {{
    background: {theme.FOAM}; border: 1px solid {theme.BORDER}; border-radius: 8px;
}}
QFrame#RecentProject:hover {{ border-color: {theme.LEAF}; }}
QFrame#RecentProject[current="true"] {{ border-color: {theme.LEAF}; }}
QFrame#ResultRow {{ border: none; border-top: 1px solid {theme.BORDER}; border-radius: 0; background: transparent; }}
QPushButton#PrimaryButton {{
    color: {theme.WHITE}; border: none; border-radius: 9px; padding: 9px 20px; font-weight: 600;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {theme.LEAF}, stop:1 {theme.OCEAN});
}}
QPushButton#PrimaryButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {theme.LEAF_DARK}, stop:1 {theme.OCEAN_DARK});
}}
QPushButton#SecondaryButton {{
    color: {theme.INK}; background: {theme.WHITE}; border: 1px solid {theme.BORDER_STRONG};
    border-radius: 9px; padding: 8px 18px; font-weight: 600;
}}
QPushButton#SecondaryButton:hover {{ background: {theme.FOAM}; border-color: {theme.BORDER_HOVER}; }}
QPushButton#SecondaryButton:pressed {{ background: {theme.MINT}; }}
"""


def _result_title(category: str, processes: list[str]) -> str:
    """e.g. "Vegetation · NDVI, EVI"; "Analysis result" when neither is known."""
    shown = ", ".join(processes[:3]) + ("…" if len(processes) > 3 else "")
    label = category_label(category) if category else ""
    return " · ".join(part for part in (label, shown) if part) or "Analysis result"


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


def analyses_by_type(records: list[AnalysisRecordDTO]) -> list[tuple[str, int]]:
    """(type, number of analyses) for the project's records, the most frequent first."""
    counts: dict[str, int] = {}
    for record in records:
        label = category_label(record.category) or "Other"
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda item: -item[1])  # stable: ties keep their first appearance


def main_metric_series(records: list[AnalysisRecordDTO]) -> tuple[str, list[tuple[str, float]]]:
    """The number recorded by the most analyses (the newest analysis decides a tie) and its values,
    oldest first, as (date shown, value) pairs; ("", []) when no analysis recorded a number."""
    newest_first = sorted(records, key=lambda record: record.created_at, reverse=True)
    counts: dict[str, int] = {}
    for record in newest_first:
        for name in record.metrics:
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return "", []
    name = max(counts, key=counts.get)  # max keeps the first (newest) name among equals
    points = [(_short_date(record.created_at), float(record.metrics[name]))
              for record in reversed(newest_first) if name in record.metrics]
    return name, points


def _short_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b")
    except (TypeError, ValueError):
        return iso or ""


class GlanceTile(QFrame):
    """One count of the project at a glance: the number, and what it counts under it (left-aligned)."""

    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("GlanceTile")
        self.value = QLabel("–", objectName="GlanceValue")
        self.label = QLabel(label, objectName="ItemMeta")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(0)
        layout.addWidget(self.value)
        layout.addWidget(self.label)

    def set_value(self, value: int | None) -> None:
        """The count, or "–" while it is not known (yet)."""
        self.value.setText("–" if value is None else f"{value:,}")


GLANCE = (("downloads", "Downloads"), ("analyses", "Analyses run"), ("maps", "Saved result maps"),
          ("explanations", "AI explanations"), ("reports", "PDF reports"))


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
    """Start page after sign-in. Clicking a recent project emits ``open_recent``; clicking a result
    map emits ``open_result``. With a ``facade``, the open project's result maps are drawn (in the
    background) further down the page."""

    open_recent = pyqtSignal(str)        # a recent project's folder
    open_result = pyqtSignal(str)        # a result GeoTIFF to open in the viewer
    new_project_requested = pyqtSignal()  # "Create project" button
    open_project_requested = pyqtSignal()  # "Open project" button

    def __init__(self, facade: IBusinessFacade | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(STYLESHEET)
        self._facade = facade
        self._map_pictures: dict[str, QImage | None] = {}  # drawn result maps, by GeoTIFF: drawn once
        self._maps_for = ""  # the project whose maps are being shown (answers for another are dropped)
        self.recent_items: list[RecentProjectItem] = []
        self.result_rows: list[ResultRow] = []

        self.greeting = QLabel(objectName="Title")

        # ---- quick actions, top-left: create or open a project
        self.create_project_button = QPushButton("＋  Create project", objectName="PrimaryButton")
        self.create_project_button.setToolTip("Start a new project (its downloads and analysis results are kept in it)")
        self.open_project_button = QPushButton("Open project", objectName="SecondaryButton")
        self.open_project_button.setToolTip("Open an existing project folder on this computer")
        for button in (self.create_project_button, self.open_project_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_project_button.clicked.connect(self.new_project_requested)
        self.open_project_button.clicked.connect(self.open_project_requested)
        self.project_actions_row = QHBoxLayout()
        self.project_actions_row.setSpacing(10)
        self.project_actions_row.addWidget(self.create_project_button)
        self.project_actions_row.addWidget(self.open_project_button)
        self.project_actions_row.addStretch(1)

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
        column.addSpacing(12)
        column.addLayout(self.project_actions_row)  # create / open a project, top-left
        column.addSpacing(16)
        column.addWidget(self.project_heading)  # just after the welcome
        column.addSpacing(20)
        column.addWidget(results_panel)
        # ---- further down (scrolling): the project at a glance
        self.glance_panel, _, glance = _panel("At a glance")
        self.glance: dict[str, GlanceTile] = {key: GlanceTile(label) for key, label in GLANCE}
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for tile in self.glance.values():
            tiles.addWidget(tile, 1)
        glance.addLayout(tiles)
        column.addSpacing(16)
        column.addWidget(self.glance_panel)
        # ---- charts of the project's analyses
        self.charts_panel, _, charts = _panel("Charts")
        self.types_title = QLabel("Analyses by type", objectName="ItemTitle")
        self.types_chart = CategoryBarChart()
        self.trend_title = QLabel(objectName="ItemTitle")
        self.trend_chart = MetricTrendChart()
        for widget in (self.types_title, self.types_chart):
            charts.addWidget(widget)
        charts.addSpacing(8)
        for widget in (self.trend_title, self.trend_chart):
            charts.addWidget(widget)
        column.addSpacing(16)
        column.addWidget(self.charts_panel)
        # ---- and the pictures of its saved results
        self.maps_panel, _, maps = _panel("Result maps")
        self.maps_note = QLabel(objectName="ItemMeta")
        self.maps_note.setWordWrap(True)
        self.gallery = ResultGallery()
        self.gallery.open_requested.connect(self.open_result)
        maps.addWidget(self.maps_note)
        maps.addWidget(self.gallery)
        column.addSpacing(16)
        column.addWidget(self.maps_panel)
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
        self._show_charts()
        self._load_glance()
        self._load_maps()
        hidden = len(self._results) - len(self.result_rows)
        self.see_more.setVisible(hidden > 0)
        if hidden > 0:
            self.see_more.setText(f"See more ({hidden} more)")
            self.see_more.setToolTip(f"All {len(self._results)} analysis results of {current.name}")

    def _show_charts(self) -> None:
        """The charts of the open project's analyses (hidden without an open project)."""
        self.charts_panel.setVisible(self._current is not None)
        self.types_chart.set_counts(analyses_by_type(self._results))
        name, points = main_metric_series(self._results)
        self.trend_title.setText(f"{name} over time" if name else "Numbers over time")
        self.trend_chart.set_series(name, points)

    # ------------------------------------------------------------- at a glance
    def _load_glance(self) -> None:
        """The project's counts: its analyses at once, the rest from the facade in the background
        (the saved maps are counted when they are listed for the gallery)."""
        project = self._current
        self.glance_panel.setVisible(project is not None)
        for tile in self.glance.values():
            tile.set_value(None)
        if project is None:
            return
        self.glance["analyses"].set_value(len(self._results))
        if self._facade is None:
            return
        wanted = project.id
        run_task(self, self._facade.list_analysis_datasets,
                 on_success=lambda datasets: self._set_glance(wanted, downloads=len(list(datasets))))
        run_task(self, self._facade.list_explanations,
                 on_success=lambda files: self._set_glance(wanted, explanations=files))

    def _set_glance(self, project_id: str, downloads: int | None = None, explanations=None) -> None:
        if self._current is None or project_id != self._current.id:
            return  # another project was opened meanwhile
        if downloads is not None:
            self.glance["downloads"].set_value(downloads)
        if explanations is not None:
            files = list(explanations)
            self.glance["explanations"].set_value(len(files))
            self.glance["reports"].set_value(sum(1 for item in files if item.report_path))

    # ------------------------------------------------------------- result maps
    def _load_maps(self) -> None:
        """List the open project's saved results in the background, then draw their maps."""
        project = self._current
        self.maps_panel.setVisible(project is not None and self._facade is not None)
        if project is None or self._facade is None:
            self._maps_for = ""
            return
        self._maps_for = project.id
        if not self.gallery.tiles:
            self.maps_note.setText("Looking for the project's result maps…")
        run_task(self, self._facade.list_saved_results,
                 on_success=lambda results, wanted=project.id: self._on_saved_results(wanted, results),
                 on_error=lambda exc: self.maps_note.setText(f"The result maps could not be listed: {exc}"))

    def _on_saved_results(self, project_id: str, results) -> None:
        if project_id != self._maps_for:
            return  # another project was opened meanwhile
        results = list(results)
        self.glance["maps"].set_value(len(results))
        shown = results[:MAPS_SHOWN]
        name = self._current.name if self._current is not None else "the project"
        self.maps_note.setText(
            "" if shown else f"Save an analysis result of {name} (Save result, or Explain with AI) to see its map here.")
        self.maps_note.setVisible(not shown)
        self.gallery.set_maps([(r.output_path, _result_title(r.category, r.processes), format_when(r.created_at))
                               for r in shown])
        for result in shown:
            path = result.output_path
            if path in self._map_pictures:
                self.gallery.set_picture(path, self._map_pictures[path])
                continue
            run_task(self, self._facade.get_map_layers, result, MAP_PICTURE_SIZE,
                     on_success=lambda layers, path=path, wanted=project_id: self._on_map_drawn(wanted, path, layers),
                     on_error=lambda exc, path=path, wanted=project_id: self._on_map_drawn(wanted, path, []))

    def _on_map_drawn(self, project_id: str, path: str, layers) -> None:
        image = rgba_to_image(layers[0].data) if layers else None
        self._map_pictures[path] = image
        if project_id == self._maps_for:
            self.gallery.set_picture(path, image)

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
