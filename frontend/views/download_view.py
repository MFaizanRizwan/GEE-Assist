"""Downloads page (UC-05 Fetch Data): live speed, statistics and every download job.

Sections:
  QUEUED             the running download and those waiting for it
  PAUSED             paused or failed downloads (Start resumes, Retry retries failed chunks)
  COMPLETED HISTORY  finished downloads; the green button opens the dataset folder

The page polls the facade twice a second, also while it is hidden, so the speed graph
keeps a continuous history (like Task Manager).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.config.download_settings import MAX_CHUNK_SIZE_MB, MIN_CHUNK_SIZE_MB
from backend.dto import DownloadJobDTO, FormDTO
from backend.dto.download_dto import JOB_COMPLETED, JOB_FAILED, JOB_PAUSED, JOB_QUEUED, JOB_RUNNING
from backend.exceptions import GeeAssistError
from frontend import accent, form_theme, layout_mode, palette, theme, theming
from frontend.download_format import format_size, format_speed
from frontend.widgets.download_rows import CollapsibleSection, CompletedRow, JobRow
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.source_card import SourceCard
from frontend.widgets.speed_chart import SpeedChart
from frontend.workers.task_worker import run_task

REFRESH_MS = 500
NONE = "–"   # shown when no download is running

def _stylesheet():
    return f"""
#DownloadPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#StatsCard, QFrame#DownloadSection {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px;
}}
QFrame#StatsCard QLabel, QFrame#DownloadSection QLabel {{ background: transparent; }}
QLabel#StatName {{ color: {theme.MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#StatValue {{ color: {theme.INK}; font-size: 15pt; }}
QLabel#ChunkSetting {{ color: {theme.MUTED}; font-size: 9pt; }}
QFrame#SectionHeader {{
    border: none; border-bottom: 1px solid {form_theme.HEADER_LINE};
    border-top-left-radius: 12px; border-top-right-radius: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {form_theme.HEADER_GREEN}, stop:1 {form_theme.HEADER_BLUE});
}}
QLabel#SectionHeaderText {{ color: {theme.INK}; font-weight: 600; letter-spacing: 0.6px; }}
QToolButton#SectionToggle {{ border: none; background: transparent; padding: 2px; }}
QFrame#JobRow {{ border: none; border-top: 1px solid {theme.BORDER}; background: transparent; }}
QLabel#SatelliteIcon {{ font-family: "Segoe UI Emoji"; font-size: 20pt; }}
QLabel#JobTitle {{ color: {theme.INK}; font-size: 11pt; }}
QLabel#JobStatus {{ color: {theme.INK}; font-weight: 600; letter-spacing: 0.4px; }}
QLabel#JobEta, QLabel#JobSize, QLabel#JobWhen {{ color: {theme.TEXT}; }}
QLabel#JobError {{ color: {theme.ERROR}; font-size: 9pt; }}
QProgressBar#JobProgress {{ background: {theme.PROGRESS_TRACK}; border: none; border-radius: 4px; }}
QProgressBar#JobProgress::chunk {{
    border-radius: 4px;
    background: {theme.ACCENT_SOLID};
}}
QProgressBar#JobProgress[state="paused"]::chunk {{ background: {theme.PROGRESS_PAUSED}; }}
QProgressBar#JobProgress[state="failed"]::chunk {{ background: {theme.PROGRESS_FAILED}; }}
QPushButton#OpenButton {{
    color: {theme.ACCENT_TEXT}; font-size: 11pt; border: none; border-radius: 6px; padding: 0;
    background: {theme.ACCENT_SOLID};
}}
QPushButton#OpenButton:hover {{ background: {theme.ACCENT_SOLID_HOVER}; }}
QPushButton#ViewButton {{
    color: {theme.INK}; background: {theme.WHITE}; border: 1px solid {theme.BORDER_STRONG};
    border-radius: 6px; padding: 0 14px; font-size: 9.5pt;
}}
QPushButton#ViewButton:hover {{ background: {theme.FOAM}; border-color: {theme.BORDER_HOVER}; }}
QPushButton#ViewButton:disabled {{ color: {theme.SUBTLE}; border-color: {theme.BORDER}; }}
QFrame#DownloadFooter {{ background: {theme.WHITE}; border-top: 1px solid {theme.BORDER}; }}
QLabel#FooterText {{ color: {theme.MUTED}; font-size: 9pt; }}
"""


# ----------------------------------------------------------------------------- modern layout
# A transfer-manager look (View > Layout > Modern): flat cards, hairline borders, mono figures
# and a lime accent. Unlike the modern query form it follows the chosen theme, so each theme
# has its own set of colours with the same keys.
_MODERN_COLORS = {
    "light": dict(
        page="#F4F6F3", card="#FFFFFF", field="#F8FAF7", border="#E3E8E2", border_strong="#CFD7CD",
        border_hover="#AEBBAB", ink="#111A15", text="#2B3A33", muted="#5F6F67", subtle="#8A988F",
        accent="#84CC16", accent_dk="#65A30D", accent_text="#4D7C0F", accent_soft="#F0F8E1",
        on_accent="#132006", second="#0284C7", track="#E8EDE6", grid="#E3E8E2",
        paused="#A3AFA6", failed="#E3A79F", error="#C0392B", success="#3F7A0C",
    ),
    "dark-green": dict(
        page="#0B1210", card="#0E1613", field="#111B17", border="#25332C", border_strong="#324239",
        border_hover="#45594E", ink="#F3F8F5", text="#E7EEEA", muted="#93A79D", subtle="#6E8278",
        accent="#A6E22E", accent_dk="#8CC81F", accent_text="#A6E22E", accent_soft="#1B2A1C",
        on_accent="#0E1613", second="#4FB3E8", track="#1B2621", grid="#1F2B26",
        paused="#6E8278", failed="#D08378", error="#FF8A80", success="#A6E22E",
    ),
    "dark-grey": dict(
        page="#111111", card="#181818", field="#1C1C1C", border="#2A2A2A", border_strong="#383838",
        border_hover="#4D4D4D", ink="#F2F2F2", text="#D9D9D9", muted="#A0A0A0", subtle="#7A7A7A",
        accent="#A6E22E", accent_dk="#8CC81F", accent_text="#A6E22E", accent_soft="#24291D",
        on_accent="#111111", second="#5DB8EA", track="#262626", grid="#262626",
        paused="#7A7A7A", failed="#D08A80", error="#FF8A80", success="#A6E22E",
    ),
}
def _mc() -> dict:
    """The modern colours for the active theme; the accent follows the theme like every button."""
    colors = dict(_MODERN_COLORS.get(palette.THEME,
                                     _MODERN_COLORS["dark-green" if palette.IS_DARK else "light"]))
    if palette.THEME in palette.THREE_COLOUR_THEMES:  # a three-colour theme: its own surfaces and text
        p = palette.ACTIVE
        colors.update(page=p["PAGE_BG"], card=p["WHITE"], field=p["FIELD_BG"], border=p["BORDER"],
                      border_strong=p["BORDER_STRONG"], border_hover=p["BORDER_HOVER"], ink=p["INK"],
                      text=p["TEXT"], muted=p["MUTED"], subtle=p["SUBTLE"], accent_soft=p["ACCENT_SOFT"],
                      second=p["OCEAN"], track=p["PROGRESS_TRACK"], grid=p["CHART_GRID"],
                      paused=p["PROGRESS_PAUSED"], failed=p["PROGRESS_FAILED"], error=p["ERROR"],
                      success=p["SUCCESS"])
    colors.update(accent=accent.SOLID, accent_dk=accent.SOLID_HOVER, accent_text=accent.SOLID,
                  on_accent=accent.TEXT)
    return colors
MONO = "Consolas"
SIDE_WIDTH = 300

def _modern_stylesheet():
    MC = _mc()
    return f"""
#DownloadPage, QWidget#DownloadContent {{ background: {MC['page']}; }}
#DownloadPage QScrollArea {{ background: {MC['page']}; border: none; }}
#DownloadPage QLabel {{ background: transparent; color: {MC['text']}; }}

/* ---- header ---- */
QLabel#PageEyebrow {{ color: {MC['muted']}; font-family: "{MONO}"; font-size: 8pt; letter-spacing: 1.5px; }}
QLabel#PageTitle {{ color: {MC['ink']}; font-family: "{theme.SANS}"; font-size: 18pt; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {MC['muted']}; font-size: 9.5pt; }}

/* ---- cards ---- */
QFrame#StatsCard, QFrame#DownloadSection {{
    background: {MC['card']}; border: 1px solid {MC['border']}; border-radius: 10px;
}}
QFrame#StatsCard QLabel, QFrame#DownloadSection QLabel {{ background: transparent; }}
QLabel#CardTitle {{ color: {MC['ink']}; font-weight: 700; font-size: 10.5pt; }}
QLabel#LiveDot {{ color: {MC['accent']}; font-size: 10pt; }}

/* ---- left column: Source dataset and Transfer settings ---- */
QFrame#SideCard {{ background: {MC['card']}; border: 1px solid {MC['border']}; border-radius: 10px; }}
QFrame#SideCard QLabel {{ background: transparent; }}
QFrame#SourceHero {{ background: {MC['field']}; border: 1px solid {MC['border']}; border-radius: 8px; }}
QLabel#SourceSub {{ color: {MC['muted']}; font-family: "{MONO}"; font-size: 8pt; }}
QLabel#SourceValue {{ color: {MC['ink']}; font-family: "{MONO}"; font-size: 9.5pt; }}
QLabel#SourceTotal {{ color: {MC['ink']}; font-family: "{MONO}"; font-size: 10pt; font-weight: 700; }}
QLabel#Coordinates {{ color: {MC['text']}; font-family: "{MONO}"; font-size: 8.5pt; background: transparent; }}
QScrollArea#CoordinateList {{ background: {MC['field']}; border: 1px solid {MC['border']}; border-radius: 8px; }}
QScrollArea#CoordinateList > QWidget > QWidget {{ background: {MC['field']}; }}
QScrollArea#CoordinateList QLabel#Coordinates {{ padding: 8px 10px; }}
QFrame#CardLine {{ background: {MC['border']}; border: none; }}

/* ---- stat tiles ---- */
QFrame#StatTiles {{ background: transparent; border: none; border-top: 1px solid {MC['border']};
    border-bottom: 1px solid {MC['border']}; border-radius: 0; }}
QFrame#StatTile {{ background: transparent; border: none; border-right: 1px solid {MC['border']}; border-radius: 0; }}
QFrame#StatTile[last="true"] {{ border-right: none; }}
QLabel#StatName {{ color: {MC['muted']}; font-family: "{MONO}"; font-size: 7.5pt; letter-spacing: 1px; }}
QLabel#StatValue {{ color: {MC['ink']}; font-family: "{MONO}"; font-size: 14pt; }}

/* ---- chart legend and chunk setting ---- */
QLabel#LegendSpeed {{ color: {MC['accent_text']}; font-size: 9pt; }}
QLabel#LegendAverage {{ color: {MC['second']}; font-size: 9pt; }}
QLabel#ChartCaption {{ color: {MC['subtle']}; font-family: "{MONO}"; font-size: 7.5pt; letter-spacing: 1px; }}
QLabel#ChunkSetting {{ color: {MC['text']}; font-family: "{MONO}"; font-size: 9pt; }}

/* ---- buttons ---- */
#DownloadPage QPushButton#SecondaryButton {{
    color: {MC['text']}; background: {MC['field']}; border: 1px solid {MC['border_strong']};
    border-radius: 7px; padding: 5px 6px; font-size: 9pt;
}}
#DownloadPage QPushButton#SecondaryButton:hover {{ background: {MC['accent_soft']}; border-color: {MC['border_hover']}; }}
#DownloadPage QPushButton#SecondaryButton:pressed {{ background: {MC['accent_soft']}; }}
#DownloadPage QPushButton#SecondaryButton:disabled {{ color: {MC['subtle']}; background: transparent; border-color: {MC['border']}; }}
QPushButton#ViewButton {{
    color: {MC['text']}; background: {MC['field']}; border: 1px solid {MC['border_strong']};
    border-radius: 7px; padding: 0 14px; font-size: 9pt;
}}
QPushButton#ViewButton:hover {{ background: {MC['accent_soft']}; border-color: {MC['border_hover']}; }}
QPushButton#ViewButton:disabled {{ color: {MC['subtle']}; background: transparent; border-color: {MC['border']}; }}
QPushButton#OpenButton {{
    color: {MC['on_accent']}; font-size: 10pt; font-weight: 700; border: none; border-radius: 7px; padding: 0;
    background: {MC['accent']};
}}
QPushButton#OpenButton:hover {{ background: {MC['accent_dk']}; }}

/* ---- sections (Queued, Paused, Completed history) ---- */
QFrame#SectionHeader {{ background: transparent; border: none; border-radius: 0; }}
QLabel#SectionHeaderText {{ color: {MC['ink']}; font-weight: 700; font-size: 10pt; letter-spacing: 0.8px; }}
QToolButton#SectionToggle {{ border: 1px solid {MC['border_strong']}; border-radius: 6px; background: {MC['field']}; padding: 3px; }}
QToolButton#SectionToggle:hover {{ border-color: {MC['border_hover']}; }}
QWidget#SectionBody {{ background: transparent; }}
#DownloadPage QLabel#Muted {{ color: {MC['muted']}; }}
QFrame#JobRow {{ border: none; border-top: 1px solid {MC['border']}; border-radius: 0; background: transparent; }}
QFrame#JobRow:hover {{ background: {MC['field']}; }}
QLabel#SatelliteIcon {{ font-family: "Segoe UI Emoji"; font-size: 16pt; }}
QLabel#JobTitle {{ color: {MC['ink']}; font-size: 10pt; font-weight: 700; }}
QLabel#JobStatus {{ color: {MC['accent_text']}; font-family: "{MONO}"; font-size: 8.5pt; letter-spacing: 0.6px; }}
QLabel#JobStatus[state="paused"], QLabel#JobStatus[state="queued"] {{ color: {MC['muted']}; }}
QLabel#JobStatus[state="failed"] {{ color: {MC['error']}; }}
QLabel#JobEta, QLabel#JobSize, QLabel#JobWhen {{ color: {MC['text']}; font-family: "{MONO}"; font-size: 9pt; }}
QLabel#JobError {{ color: {MC['error']}; font-size: 9pt; }}
QProgressBar#JobProgress {{ background: {MC['track']}; border: none; border-radius: 3px; }}
QProgressBar#JobProgress::chunk {{ border-radius: 3px; background: {MC['accent']}; }}
QProgressBar#JobProgress[state="paused"]::chunk {{ background: {MC['paused']}; }}
QProgressBar#JobProgress[state="failed"]::chunk {{ background: {MC['failed']}; }}

/* ---- footer ---- */
QFrame#DownloadFooter {{ background: {MC['page']}; border-top: 1px solid {MC['border']}; }}
QLabel#FooterText {{ color: {MC['muted']}; font-size: 8.5pt; }}

/* ---- scrollbars ---- */
#DownloadPage QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
#DownloadPage QScrollBar::handle:vertical {{ background: {MC['border_strong']}; border-radius: 4px; min-height: 30px; }}
#DownloadPage QScrollBar::handle:vertical:hover {{ background: {MC['border_hover']}; }}
#DownloadPage QScrollBar::add-line, #DownloadPage QScrollBar::sub-line {{ height: 0; }}
"""


class DownloadView(QWidget):
    """Shows all downloads and lets the user pause, resume, retry, cancel and open them."""

    download_started = pyqtSignal(object)  # DownloadJobDTO
    view_requested = pyqtSignal(str)       # path of a downloaded GeoTIFF to show

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DownloadPage")
        self._modern = layout_mode.is_modern()
        theming.styled(self, _modern_stylesheet if self._modern else _stylesheet)
        self._facade = facade
        self._rows: dict[str, tuple[CollapsibleSection, QWidget]] = {}
        self._peak = 0.0

        title = QLabel("Downloads", objectName="PageTitle")
        subtitle = QLabel(
            "Datasets from Google Earth Engine, fetched in chunks and merged into one GeoTIFF as they arrive.",
            objectName="PageSubtitle",
        )
        self.banner = StatusBanner()
        self.banner.setContentsMargins(10, 6, 10, 6)  # wrapped labels ignore stylesheet padding

        content = QWidget(objectName="DownloadContent")
        column = QVBoxLayout(content)
        column.setContentsMargins(24, 20, 24, 20)
        column.setSpacing(14)
        if self._modern:
            column.setContentsMargins(22, 18, 22, 18)
            column.setSpacing(16)
            heading = QVBoxLayout()
            heading.setSpacing(2)
            heading.addWidget(QLabel("TRANSFER MANAGER", objectName="PageEyebrow"))
            heading.addWidget(title)
            heading.addWidget(subtitle)
            subtitle.setWordWrap(True)
            column.addLayout(heading)
        else:
            column.addWidget(title)
            column.addWidget(subtitle)
        column.addWidget(self.banner)
        self.queued = CollapsibleSection("QUEUED", "Nothing is downloading. Start a download from Query Input.")
        self.paused = CollapsibleSection("PAUSED", "No paused downloads.")
        self.completed = CollapsibleSection("COMPLETED HISTORY", "Finished downloads appear here.")
        sections = (self.queued, self.paused, self.completed)
        if self._modern:
            # Source dataset and transfer settings on the left, the live transfer and the jobs on the right.
            self.source = SourceCard()
            side = QVBoxLayout()
            side.setSpacing(16)
            side.addWidget(self.source)
            side.addWidget(self._build_transfer_settings())
            side.addStretch(1)
            side_widget = QWidget()
            side_widget.setLayout(side)
            side_widget.setFixedWidth(SIDE_WIDTH)
            main = QVBoxLayout()
            main.setSpacing(16)
            main.addWidget(self._build_modern_stats())
            for section in sections:
                main.addWidget(section)
            main.addStretch(1)
            body = QHBoxLayout()
            body.setSpacing(16)
            body.addWidget(side_widget, 0, Qt.AlignmentFlag.AlignTop)
            body.addLayout(main, 1)
            column.addLayout(body, 1)
        else:
            self.source = None
            column.addWidget(self._build_stats())
            for section in sections:
                column.addWidget(section)
            column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._build_footer())

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ------------------------------------------------------------- building
    def _build_stats(self) -> QFrame:
        card = QFrame(objectName="StatsCard")
        self.chart = SpeedChart()
        self.stats: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        names = ("CURRENT", "PEAK", "DOWNLOADED", "REMAINING", "DISK USAGE", "MERGING SPEED")
        for index, name in enumerate(names):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(QLabel(f"{name}:", objectName="StatName"))
            value = QLabel("–", objectName="StatValue")
            cell.addWidget(value)
            self.stats[name] = value
            grid.addLayout(cell, index // 3, index % 3)

        self.chunk_setting = QLabel(objectName="ChunkSetting")
        self.change_chunk = QPushButton("Change…", objectName="SecondaryButton")
        self.change_chunk.setCursor(Qt.CursorShape.PointingHandCursor)
        self.change_chunk.setToolTip("Chunk size for downloads started from now on")
        setting = QHBoxLayout()
        setting.addStretch(1)
        setting.addWidget(self.chunk_setting)
        setting.addWidget(self.change_chunk)

        figures = QVBoxLayout()
        figures.addLayout(grid)
        figures.addStretch(1)
        figures.addLayout(setting)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 14, 18, 14)
        layout.setSpacing(20)
        layout.addWidget(self.chart, 3)
        layout.addLayout(figures, 2)
        self.change_chunk.clicked.connect(self.change_chunk_size)
        return card

    def _build_modern_stats(self) -> QFrame:
        """The same figures as ``_build_stats``, laid out as a transfer-manager card:
        a title row, a strip of stat tiles, the speed chart with its legend, and the chunk setting."""
        card = QFrame(objectName="StatsCard")

        heading = QHBoxLayout()
        heading.setContentsMargins(18, 14, 18, 12)
        heading.setSpacing(8)
        heading.addWidget(QLabel("●", objectName="LiveDot"))
        heading.addWidget(QLabel("Live transfer", objectName="CardTitle"))
        heading.addStretch(1)

        tiles = QFrame(objectName="StatTiles")
        strip = QHBoxLayout(tiles)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(0)
        self.stats: dict[str, QLabel] = {}
        names = ("CURRENT", "PEAK", "DOWNLOADED", "REMAINING", "DISK USAGE", "MERGING SPEED")
        for index, name in enumerate(names):
            tile = QFrame(objectName="StatTile")
            tile.setProperty("last", index == len(names) - 1)
            cell = QVBoxLayout(tile)
            cell.setContentsMargins(16, 12, 16, 12)
            cell.setSpacing(6)
            cell.addWidget(QLabel(name, objectName="StatName"))
            value = QLabel(NONE, objectName="StatValue")
            cell.addWidget(value)
            self.stats[name] = value
            strip.addWidget(tile, 1)

        self.chart = SpeedChart()
        self.chart.setMinimumHeight(190)
        self.chart.set_colors(
            background=MC["card"], border=MC["card"], grid=MC["grid"],
            speed=MC["accent"], average=MC["second"], radius=0,
            tooltip="Download speed over the last minute (lime) and the download's average speed (blue)",
        )
        legend = QHBoxLayout()
        legend.setSpacing(16)
        legend.addWidget(QLabel("━  Download speed", objectName="LegendSpeed"))
        legend.addWidget(QLabel("━  Average speed", objectName="LegendAverage"))
        legend.addStretch(1)
        legend.addWidget(QLabel("SPEED / LAST MINUTE", objectName="ChartCaption"))
        plot = QVBoxLayout()
        plot.setContentsMargins(18, 14, 18, 10)
        plot.setSpacing(6)
        plot.addLayout(legend)
        plot.addWidget(self.chart, 1)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(heading)
        layout.addWidget(tiles)
        layout.addLayout(plot, 1)
        return card

    def _build_transfer_settings(self) -> QFrame:
        """The chunk size for new downloads (modern layout's left column)."""
        card = QFrame(objectName="SideCard")
        self.chunk_setting = QLabel(objectName="ChunkSetting")
        self.change_chunk = QPushButton("Change…", objectName="SecondaryButton")
        self.change_chunk.setCursor(Qt.CursorShape.PointingHandCursor)
        self.change_chunk.setToolTip("Chunk size for downloads started from now on")
        value = QHBoxLayout()
        value.addWidget(self.chunk_setting, 1)
        value.addWidget(self.change_chunk)
        hint = QLabel("Used for downloads started from now on.", objectName="Muted")
        hint.setWordWrap(True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Transfer settings", objectName="CardTitle"))
        layout.addWidget(QLabel("CHUNK SIZE", objectName="StatName"))
        layout.addLayout(value)
        layout.addWidget(hint)
        self.change_chunk.clicked.connect(self.change_chunk_size)
        return card

    def _build_footer(self) -> QFrame:
        footer = QFrame(objectName="DownloadFooter")
        self.location = QLabel(objectName="FooterText")
        self.connection = QLabel("GEE Connection: checking…", objectName="FooterText")
        row = QHBoxLayout(footer)
        row.setContentsMargins(24, 6, 24, 6)
        row.addWidget(self.location, 1)
        row.addWidget(self.connection)
        return footer

    # ------------------------------------------------------------- lifecycle
    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self.refresh()
        self.check_connection()  # again on every visit, so fixing the setup shows up

    # ------------------------------------------------------------- actions
    def start(self, form: FormDTO) -> None:
        """Start downloading a kept request (called from Query Input)."""
        self.banner.show_info("Preparing the download…")
        run_task(self, self._facade.start_download, form, on_success=self._on_started, on_error=self._show_error)

    def check_connection(self) -> None:
        run_task(self, self._facade.is_gee_available, on_success=self._on_connection, on_error=lambda _: self._on_connection(False))

    def refresh(self) -> None:
        jobs = [job for job in self._facade.list_downloads() if job.status != "cancelled"]
        running = next((job for job in jobs if job.status == JOB_RUNNING), None)
        self._update_stats(jobs, running)

        queued = ([running] if running else []) + [job for job in jobs if job.status == JOB_QUEUED]
        paused = [job for job in jobs if job.status in (JOB_PAUSED, JOB_FAILED)]
        completed = sorted((job for job in jobs if job.status == JOB_COMPLETED), key=lambda j: j.finished_at, reverse=True)
        self._sync(self.queued, queued, JobRow)
        self._sync(self.paused, paused, JobRow)
        self._sync(self.completed, completed, CompletedRow)
        visible = {job.id for job in queued + paused + completed}
        for job_id in [i for i in self._rows if i not in visible]:
            self._remove_row(job_id)

        latest = jobs[-1] if jobs else None
        if self.source is not None:
            self.source.show_job(running or latest)
        area = latest.request.aoi_name if latest and latest.request and latest.request.aoi_name else ""
        self.location.setText(f"GEE-Assist  |  Location: {area}" if area else "GEE-Assist")

    def _on_started(self, job: DownloadJobDTO) -> None:
        self.banner.show_success(
            f"Download started: {job.name} ({format_size(job.total_bytes)} in {job.total_chunks} "
            f"chunk{'s' if job.total_chunks != 1 else ''})."
        )
        self.refresh()
        self.download_started.emit(job)

    def _on_connection(self, available: bool) -> None:
        if available:
            self.connection.setText("GEE Connection: Active")
            self.connection.setStyleSheet(f"color: {MC['success'] if self._modern else theme.SUCCESS};")
        else:
            self.connection.setText(
                "GEE Connection: not available (check GEE_PROJECT, `earthengine authenticate` "
                "and that the Earth Engine API is enabled for the project)"
            )
            self.connection.setStyleSheet(f"color: {MC['error'] if self._modern else theme.ERROR};")

    def _start_job(self, job: DownloadJobDTO) -> None:
        action = self._facade.retry_failed_chunks if job.status == JOB_FAILED else self._facade.resume_download
        self._call(action, job)

    def _pause_job(self, job: DownloadJobDTO) -> None:
        self._call(self._facade.pause_download, job)

    def _cancel_job(self, job: DownloadJobDTO) -> None:
        answer = QMessageBox.question(
            self, "Cancel download",
            f"Cancel downloading {job.name}?\nThe files downloaded so far will be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            run_task(self, self._facade.cancel_download, job, on_success=lambda _: self.refresh(), on_error=self._show_error)

    def _open_job(self, job: DownloadJobDTO) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(job.folder))

    def choose_save_folder(self, job: DownloadJobDTO) -> str:
        return QFileDialog.getExistingDirectory(self, f"Save {job.name} to", str(Path.home()))

    def save_copy(self, job: DownloadJobDTO) -> None:
        """Copy the finished dataset to a folder the user chooses (copying a big GeoTIFF takes a while)."""
        folder = self.choose_save_folder(job)
        if not folder:
            return
        self.banner.show_info(f"Saving a copy of {job.name} to {folder}…")
        run_task(self, self._facade.save_download_copy, job, folder,
                 on_success=lambda path: self.banner.show_success(f"Saved a copy to {path}"),
                 on_error=self._show_error)

    def change_chunk_size(self) -> None:
        current = self._facade.get_chunk_size_mb()
        size, accepted = QInputDialog.getInt(
            self, "Chunk size", "Chunk size for new downloads (MB):", current, MIN_CHUNK_SIZE_MB, MAX_CHUNK_SIZE_MB, 50,
        )
        if accepted and size != current:
            try:
                saved = self._facade.set_chunk_size_mb(size)
            except GeeAssistError as exc:
                self._show_error(exc)
                return
            self.banner.show_info(f"New downloads will use {saved} MB chunks.")
            self._update_chunk_setting()

    def _call(self, action, job: DownloadJobDTO) -> None:
        try:
            action(job)
        except GeeAssistError as exc:
            self._show_error(exc)
        self.refresh()

    def _show_error(self, exc: Exception) -> None:
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "Something went wrong. Please try again.")

    # ------------------------------------------------------------- updating
    def _update_stats(self, jobs: list[DownloadJobDTO], running: DownloadJobDTO | None) -> None:
        speed = running.speed_bps if running else 0.0
        self.chart.add_sample(speed, running.average_speed_bps if running else 0.0)
        self._peak = max(self._peak, speed)
        merge_speed = running.merge_speed_bps if running else 0.0  # 0 while nothing is being merged
        values = {
            "CURRENT": format_speed(speed),
            "PEAK": format_speed(self._peak),
            "DOWNLOADED": format_size(running.received_bytes) if running else NONE,  # current download only
            "REMAINING": format_size(max(0, running.total_bytes - running.downloaded_bytes)) if running else NONE,
            "DISK USAGE": format_size(running.disk_bytes) if running else NONE,
            "MERGING SPEED": format_speed(merge_speed),
        }
        for name, value in values.items():
            self.stats[name].setText(value)
        self._update_chunk_setting()

    def _update_chunk_setting(self) -> None:
        self.chunk_setting.setText(f"Chunk size: {self._facade.get_chunk_size_mb()} MB")

    def _sync(self, section: CollapsibleSection, jobs: list[DownloadJobDTO], row_type) -> None:
        """Make ``section`` show one row per job, in order, reusing existing rows."""
        for position, job in enumerate(jobs):
            existing = self._rows.get(job.id)
            if existing and existing[0] is section and isinstance(existing[1], row_type):
                row = existing[1]
                row.update_job(job)
            else:
                if existing:
                    self._remove_row(job.id)
                row = self._make_row(job, row_type)
                self._rows[job.id] = (section, row)
            section.rows.removeWidget(row)
            section.rows.insertWidget(position + 1, row)  # after the "empty" label
        section.set_count(len(jobs))

    def _make_row(self, job: DownloadJobDTO, row_type) -> QWidget:
        row = row_type(job)
        if isinstance(row, JobRow):
            row.start_clicked.connect(self._start_job)
            row.pause_clicked.connect(self._pause_job)
            row.cancel_clicked.connect(self._cancel_job)
        else:
            row.open_clicked.connect(self._open_job)
            row.view_clicked.connect(lambda job: self.view_requested.emit(job.dataset.path))
            row.save_clicked.connect(self.save_copy)
        return row

    def _remove_row(self, job_id: str) -> None:
        section, row = self._rows.pop(job_id)
        section.rows.removeWidget(row)
        row.deleteLater()

