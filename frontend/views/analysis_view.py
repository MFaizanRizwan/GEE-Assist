"""Analysis page (UC-06): run analyses on downloaded datasets.

The left panel goes step by step: choose a dataset (a finished download, or any
GeoTIFF), one of the four analyses (water, vegetation, land surface temperature,
land use / land cover; one the dataset cannot run is greyed out), then its processes
as cards grouped by sub-type (see ``ProcessPicker``): those the dataset can run come
first, those it cannot are set apart below with the reason. Then their parameters,
and for before / after processes an earlier dataset to compare with. The line above "Run" says where the analysis runs:
the GPU when the computer has a dedicated NVIDIA card with CuPy, else the CPU.

The right panel shows the result: each layer drawn with its legend, the numbers
(means, areas, transitions), and buttons to save it, open it in the viewer or show it
on the map. "Explain with AI" saves it in the project and opens the AI explanation page
(see ``ExplanationView``). A result is temporary until the user saves it (“Save result”, into the project's analysis folder
they choose); an unsaved one is deleted when the next one replaces it or the app
closes. Analyses run in the background with a progress bar.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.analysis_dto import AnalysisOptionDTO, AnalysisRequestDTO, ComputeDeviceDTO, ProcessOptionDTO
from backend.dto.download_dto import DatasetDTO
from backend.dto.map_dto import MapLayerDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import GeeAssistError
from frontend import accent, fieldbook, layout_mode, palette, theme, theming
from frontend.project_paths import analysis_folder, current_project, downloads_folder
from frontend.download_format import format_size
from frontend.widgets.earth_loader import EarthLoader
from frontend.widgets.flow_layout import FlowLayout
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.map_area import MapArea
from frontend.widgets.process_picker import stylesheet as picker_stylesheet
from frontend.widgets.run_filmstrip import RunFilmstrip
from frontend.widgets.process_picker import AnalysisTile, ProcessPicker
from frontend.widgets.raster_canvas import rgba_to_image
from frontend.widgets.raster_legend import format_value
from frontend.widgets.symbology_panel import SymbologyPanel
from frontend.workers.task_worker import run_task

PANEL_WIDTH = 430
# Responsive layout: on smaller screens (e.g. 1366x768) the setup drawer narrows; once a result
# exists the drawer folds away so the map leads, and the rail reopens it.
PANEL_WIDTH_COMPACT = 360
WIDE_PAGE = 1450              # page width from which the dataset panel gets its full width
SHORT_PAGE = 720              # page height below which the header is compacted
RESULT_SPACING = 14
SIDE_WIDTH = 330             # the column beside the map: numbers, symbology, actions
RAIL_WIDTH = 64              # the setup rail; its drawer is the steps panel
FILM_SHOWN = 12              # saved results in the filmstrip
FILM_PICTURE = 220           # longest side of a filmstrip picture, in pixels
PROGRESS_POLL_MS = 100
MAP_IMAGE_SIZE = 1024

# Parameter -> (label, default, minimum, maximum, step, help).
PARAMETERS: dict[str, tuple[str, float, float, float, float, str]] = {
    "savi_l": ("SAVI soil factor L", 0.5, 0.0, 1.0, 0.05, "0 for dense vegetation, 1 for very sparse."),
    "wdrvi_alpha": ("WDRVI weight α", 0.1, 0.05, 0.5, 0.05, "0.1-0.2: lower keeps dense canopies from saturating."),
    "water_threshold": ("Water index threshold", 0.0, -0.5, 0.5, 0.05,
                        "Pixels whose MNDWI (or NDWI) is above it count as water."),
    "sar_water_db": ("Radar water threshold (dB)", -16.0, -25.0, -10.0, 0.5,
                     "Pixels with VV backscatter below it count as water."),
    "fcover_ndvi_soil": ("FCover: NDVI of bare soil", 0.2, -0.2, 0.6, 0.01, ""),
    "fcover_ndvi_veg": ("FCover: NDVI of full cover", 0.86, 0.5, 1.0, 0.01, ""),
}

def _stylesheet():
    return f"""
#AnalysisPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#AnalysisPanel, QFrame#ResultCard {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px;
}}
QFrame#AnalysisPanel QLabel, QFrame#ResultCard QLabel {{ background: transparent; }}
QFrame#AnalysisRail {{ background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}
QPushButton#RailButton {{
    color: {theme.INK}; background: {theme.WHITE}; border: 1px solid {theme.BORDER_STRONG};
    border-radius: {accent.BUTTON_RADIUS}px; padding: 8px 0; font-size: 8.5pt; font-weight: 600;
}}
QPushButton#RailButton:hover {{ background: {theme.FOAM}; }}
QPushButton#RailButton:checked {{ border-color: {theme.ACCENT_SOLID}; background: {theme.ACCENT_SOFT}; }}
QFrame#AnalysisRail QPushButton#PrimaryButton {{ padding: 8px 0; font-size: 8.5pt; }}
QFrame#FilmTile {{ background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; }}
QFrame#FilmTile:hover {{ border-color: {theme.ACCENT_SOLID}; }}
QLabel#FilmPicture {{ color: {theme.MUTED}; background: {theme.DISABLED_BG}; border-radius: 4px; }}
QLabel#FilmCaption {{ color: {theme.TEXT}; font-family: "{fieldbook.MONO}"; font-size: 9pt; }}
QLabel#StepTitle {{ color: {theme.INK}; font-weight: 700; font-size: 10.5pt; }}
QLabel#SectionTitle {{ color: {theme.MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#DeviceLine {{ color: {theme.INK}; font-weight: 600; }}
QListWidget {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 4px;
    color: {theme.TEXT};
}}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {theme.MINT}; color: {theme.INK}; }}
QLabel#SaveState {{ color: {theme.MUTED}; font-size: 9pt; }}
QLabel#SaveState[saved="true"] {{ color: {theme.SUCCESS}; }}
QComboBox, QDoubleSpinBox {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px;
    padding: 5px 8px; color: {theme.INK};
}}
QTableWidget {{
    background: {theme.WHITE}; border: none; gridline-color: {theme.TABLE_LINE}; color: {theme.TEXT};
}}
QHeaderView::section {{
    background: {theme.FIELD_BG}; color: {theme.MUTED}; border: none; border-bottom: 1px solid {theme.BORDER};
    padding: 5px 8px; font-weight: 600; font-size: 9pt;
}}
"""


# Dark theme for the Analysis page (modern layout). Scoped under #AnalysisPage so it
# overrides the light base and the process picker's own stylesheet.
_M = {
    "bg": "#0B1210", "card": "#141E1A", "panel": "#0E1613", "line": "#25332C", "line2": "#324239",
    "ink": "#F3F8F5", "text": "#E7EEEA", "muted": "#93A79D", "subtle": "#6E8278",
    "field": "#172420", "accent": "#A6E22E", "accent_soft": "#1B2A1C", "error": "#F2777A",
}
def _modern_colours() -> dict:
    """The modern page's own dark colours, or, in a three-colour theme, the theme's."""
    if palette.THEME not in palette.THREE_COLOUR_THEMES:
        return dict(_M)
    p = palette.ACTIVE
    return dict(_M, bg=p["PAGE_BG"], card=p["WHITE"], panel=p["WHITE"], line=p["BORDER"],
                line2=p["BORDER_STRONG"], ink=p["INK"], text=p["TEXT"], muted=p["MUTED"],
                subtle=p["SUBTLE"], field=p["FIELD_BG"], accent_soft=p["ACCENT_SOFT"], error=p["ERROR"])


def _modern_stylesheet():
    return """
#AnalysisPage {{ background: {bg}; }}
#AnalysisPage QLabel {{ color: {text}; }}
#AnalysisPage QLabel#PageTitle {{ color: {ink}; }}
#AnalysisPage QLabel#PageSubtitle, #AnalysisPage QLabel#Muted {{ color: {muted}; }}
QFrame#AnalysisPanel, QFrame#ResultCard {{ background: {card}; border: 1px solid {line}; }}
#AnalysisPage QLabel#StepTitle {{ color: {ink}; }}
#AnalysisPage QLabel#SectionTitle, #AnalysisPage QLabel#GroupTitle {{ color: {muted}; }}
#AnalysisPage QLabel#DeviceLine {{ color: {ink}; }}
#AnalysisPage QListWidget {{ background: {field}; border: 1px solid {line}; color: {text}; }}
#AnalysisPage QListWidget::item:selected {{ background: {accent_soft}; color: {ink}; }}
#AnalysisPage QComboBox, #AnalysisPage QDoubleSpinBox {{
    background: {field}; border: 1px solid {line2}; color: {ink};
}}
#AnalysisPage QComboBox QAbstractItemView {{
    background: {field}; color: {ink}; selection-background-color: {accent_soft}; selection-color: {ink};
}}
#AnalysisPage QTableWidget {{ background: {card}; color: {text}; gridline-color: {line}; }}
#AnalysisPage QHeaderView::section {{ background: {field}; color: {muted}; border-bottom: 1px solid {line}; }}
/* process picker */
#AnalysisPage QPushButton#AnalysisTile {{ background: {field}; color: {ink}; border: 1px solid {line}; }}
#AnalysisPage QPushButton#AnalysisTile:hover {{ background: {accent_soft}; }}
#AnalysisPage QPushButton#AnalysisTile:checked {{ background: {accent_soft}; border: 2px solid {accent}; }}
#AnalysisPage QPushButton#AnalysisTile:disabled {{ color: {subtle}; background: {card}; }}
#AnalysisPage QFrame#ProcessCard {{ background: {field}; border: 1px solid {line}; }}
#AnalysisPage QFrame#ProcessCard[available="true"]:hover {{ background: {accent_soft}; border-color: {line2}; }}
#AnalysisPage QFrame#ProcessCard[selected="true"] {{ background: {accent_soft}; border: 2px solid {accent}; }}
#AnalysisPage QFrame#ProcessCard[available="false"] {{ background: {card}; border: 1px dashed {line}; }}
#AnalysisPage QLabel#CardKey {{ color: {ink}; }}
#AnalysisPage QLabel#CardName {{ color: {text}; }}
#AnalysisPage QLabel#CardFormula {{ color: {muted}; }}
#AnalysisPage QLabel#CardCheck {{ border: 1px solid {line2}; }}
#AnalysisPage QLabel#CardCheck[on="true"] {{ background: {accent}; border-color: {accent}; }}
#AnalysisPage QLabel#SectionCan {{ color: {accent}; }}
#AnalysisPage QPushButton#SubtypeChip {{ background: {field}; color: {text}; border: 1px solid {line2}; }}
#AnalysisPage QPushButton#SubtypeChip:hover {{ background: {accent_soft}; }}
#AnalysisPage QPushButton#SubtypeChip:checked {{ background: {accent_soft}; border-color: {accent}; }}
#AnalysisPage QCheckBox {{ color: {text}; }}
#AnalysisPage QPushButton#PrimaryButton {{
    color: {on_accent}; border: none; border-radius: {radius}px;
    background: {accent};
}}
#AnalysisPage QPushButton#PrimaryButton:hover {{ background: {accent_dk}; }}
#AnalysisPage QPushButton#SecondaryButton {{ background: {field}; color: {text}; border: 1px solid {line2}; }}
#AnalysisPage QPushButton#SecondaryButton:hover {{ background: {accent_soft}; }}
#AnalysisPage QLabel#SaveState {{ color: {muted}; }}
QFrame#AnalysisRail {{ background: {card}; border: 1px solid {line}; }}
#AnalysisPage QPushButton#RailButton {{ background: {field}; color: {text}; border: 1px solid {line2}; }}
#AnalysisPage QPushButton#RailButton:hover {{ background: {accent_soft}; }}
#AnalysisPage QPushButton#RailButton:checked {{ border-color: {accent}; background: {accent_soft}; }}
#AnalysisPage QFrame#AnalysisRail QPushButton#PrimaryButton {{ padding: 8px 0; font-size: 8.5pt; }}
#AnalysisPage QFrame#FilmTile {{ background: {field}; border: 1px solid {line}; }}
#AnalysisPage QFrame#FilmTile:hover {{ border-color: {accent}; }}
#AnalysisPage QLabel#FilmPicture {{ background: {card}; color: {muted}; }}
#AnalysisPage QLabel#FilmCaption {{ color: {text}; }}
""".format(**dict(_modern_colours(), accent=accent.SOLID, accent_dk=accent.SOLID_HOVER, on_accent=accent.TEXT,
                       radius=accent.BUTTON_RADIUS))


def _shrinkable(widget: QWidget) -> QWidget:
    """May be narrower than its text (clipped), so the fixed-width panel never overflows."""
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, widget.sizePolicy().verticalPolicy())
    return widget


def _step(number: int, title: str) -> QLabel:
    return _shrinkable(QLabel(f"{number} · {title}", objectName="StepTitle"))


def _section(title: str) -> QLabel:
    return _shrinkable(QLabel(title.upper(), objectName="SectionTitle"))


def dataset_title(dataset: DatasetDTO) -> str:
    """e.g. "Sentinel-2 · 2024-06-01 to 2024-06-30"."""
    dates = " to ".join(d for d in (dataset.start_date, dataset.end_date) if d)
    return "  ·  ".join(part for part in (dataset.satellite or "Unknown sensor", dates) if part)


def device_text(device: ComputeDeviceDTO) -> str:
    return f"⚡ Runs on the GPU: {device.device_name}" if device.uses_gpu else "Runs on the CPU"


NO_PROJECT = ("Create or open a project: the datasets downloaded into it are listed here, and its "
              "analysis results are saved in it.")

class AnalysisView(QWidget):
    open_in_viewer_requested = pyqtSignal(str)               # result GeoTIFF
    show_on_map_requested = pyqtSignal(bytes, object, str)   # PNG, (west, south, east, north), title
    explain_requested = pyqtSignal(object)                   # ResultDTO to explain with Gemini
    analysis_finished = pyqtSignal(object)                   # ResultDTO of an analysis that ran successfully

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AnalysisPage")
        self._modern = layout_mode.is_modern()
        self._dark = self._modern or palette.IS_DARK  # overlays/panel follow the app theme in classical
        theming.styled(self, lambda: _stylesheet() + picker_stylesheet()
                       + (_modern_stylesheet() if self._modern else ""))
        self._facade = facade
        self.datasets: list[DatasetDTO] = []
        self.opened: list[DatasetDTO] = []               # GeoTIFFs opened from disk this session
        self.dataset: DatasetDTO | None = None
        self.options: list[AnalysisOptionDTO] = []
        self.category: str = ""
        self.analysis_tiles: dict[str, AnalysisTile] = {}
        self.param_boxes: dict[str, QDoubleSpinBox] = {}
        self.device: ComputeDeviceDTO | None = None
        self.result: ResultDTO | None = None
        self.layers: list[MapLayerDTO] = []
        self.running = False
        self._progress = 0.0
        self._loaded = False

        # ---- header
        self.title = QLabel("Analysis", objectName="PageTitle")
        self.subtitle = QLabel("Choose a dataset, the kind of analysis and its processes, then run it.",
                               objectName="PageSubtitle")
        self.banner = StatusBanner()

        # ---- step 1: dataset
        self.dataset_list = QListWidget()
        self.dataset_list.setMinimumHeight(110)
        self.dataset_list.setMaximumHeight(170)
        self.dataset_list.setIconSize(QSize(0, 0))
        self.compare_list = QListWidget()
        self.compare_list.setMaximumHeight(120)
        for widget in (self.dataset_list, self.compare_list):  # long names wrap instead of widening the panel
            widget.setWordWrap(True)
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, widget.sizePolicy().verticalPolicy())
        self.refresh_button = QPushButton("Refresh", objectName="SecondaryButton")
        self.browse_button = QPushButton("Open GeoTIFF…", objectName="SecondaryButton")
        self.dataset_note = QLabel(objectName="Muted")
        self.dataset_note.setWordWrap(True)

        # ---- step 2: one of the four analyses
        self.tiles_area = QVBoxLayout()
        self.tiles_area.setSpacing(6)
        self.category_note = QLabel(objectName="Muted")
        self.category_note.setWordWrap(True)

        # ---- step 3: processes and parameters
        self.picker = ProcessPicker()
        self.params_title = _section("Parameters")
        self.params_form = QFormLayout()
        self.params_form.setHorizontalSpacing(10)
        self.params_form.setVerticalSpacing(6)
        self.compare_title = _section("Compare with (earlier dates)")
        self.compare_note = QLabel("Before / after processes need another dataset of the same place.",
                                   objectName="Muted")
        self.compare_note.setWordWrap(True)

        # ---- device and run
        self.device_label = QLabel("Looking for a GPU…", objectName="DeviceLine")
        self.device_label.setWordWrap(True)
        self.device_detail = QLabel(objectName="Muted")
        self.device_detail.setWordWrap(True)
        self.use_gpu = QCheckBox("Use the GPU")
        self.use_gpu.setEnabled(False)
        self.run_button = QPushButton("Run analysis", objectName="PrimaryButton")
        self.progress = QProgressBar(objectName="BusyBar")
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.hide()

        panel_content = QWidget()
        column = QVBoxLayout(panel_content)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(8)
        self._step_widgets = {"data": _step(1, "Dataset"), "type": _step(2, "Analysis"),
                              "steps": _step(3, "Processes")}
        column.addWidget(self._step_widgets["data"])
        column.addWidget(self.dataset_list)
        row = QHBoxLayout()
        row.addWidget(self.refresh_button)
        row.addWidget(self.browse_button)
        column.addLayout(row)
        column.addWidget(self.dataset_note)
        column.addSpacing(6)
        column.addWidget(self._step_widgets["type"])
        column.addLayout(self.tiles_area)
        column.addWidget(self.category_note)
        column.addSpacing(6)
        column.addWidget(self._step_widgets["steps"])
        column.addWidget(self.picker)
        column.addSpacing(4)
        column.addWidget(self.params_title)
        column.addLayout(self.params_form)
        column.addWidget(self.compare_title)
        column.addWidget(self.compare_note)
        column.addWidget(self.compare_list)
        column.addStretch(1)
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel_scroll.setWidget(panel_content)
        self._panel_scroll = panel_scroll
        run_box = QVBoxLayout()
        run_box.setContentsMargins(18, 8, 18, 14)
        run_box.setSpacing(6)
        run_box.addWidget(self.device_label)
        run_box.addWidget(self.device_detail)
        run_box.addWidget(self.use_gpu)
        run_box.addWidget(self.progress)
        run_box.addWidget(self.run_button)
        panel = QFrame(objectName="AnalysisPanel")
        panel.setFixedWidth(PANEL_WIDTH)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        panel_layout.addWidget(panel_scroll, 1)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        theming.styled(divider, lambda: f"color: {theme.BORDER};")
        panel_layout.addWidget(divider)
        panel_layout.addLayout(run_box)

        # ---- results: the map (with a scale bar and floating legend), the numbers,
        # and a symbology / statistics panel beside it.
        self._current_layer: MapLayerDTO | None = None
        self.result_title = QLabel("No result yet", objectName="StepTitle")
        self.result_info = QLabel("Results appear here: the map with its legend and a scale bar, the symbology "
                                  "controls, and the numbers.", objectName="Muted")
        self.result_info.setWordWrap(True)
        self.layer_box = QComboBox()
        self.layer_box.setMinimumWidth(200)

        self.map_area = MapArea(dark=self._dark)
        self.canvas = self.map_area.canvas        # kept name: the raster canvas inside the map area
        self.canvas.setMinimumHeight(200)

        self.sym_panel = SymbologyPanel(dark=self._dark)
        self.sym_panel.changed.connect(self._recolor)
        self.sym_panel.opacity_changed.connect(self.map_area.set_opacity)

        self.metrics_table = QTableWidget(0, 2)
        self.metrics_table.setHorizontalHeaderLabels(("Result", "Value"))
        self.metrics_table.verticalHeader().hide()
        self.metrics_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.metrics_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.metrics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metrics_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.metrics_table.setMinimumHeight(80)
        self.metrics_table.setMaximumHeight(150)
        self.save_state = QLabel(objectName="SaveState")
        self.save_state.setWordWrap(True)
        self.save_button = QPushButton("Save result", objectName="PrimaryButton")
        self.save_button.setToolTip("Keep this result: its GeoTIFF (and its numbers as .json) are saved in the "
                                    "project's analysis folder")
        self.viewer_button = QPushButton("Open in viewer", objectName="SecondaryButton")
        self.map_button = QPushButton("Show on map", objectName="SecondaryButton")
        self.folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        self.explain_button = QPushButton("Explain with AI", objectName="SecondaryButton")
        self.explain_button.setToolTip("Save the result in the project and ask Gemini to explain it, from its "
                                       "GeoTIFF and the metadata before and after the analysis")

        # ---- the result leads: the map, with the project's saved runs in a filmstrip under it
        card = QFrame(objectName="ResultCard")
        result_layout = QVBoxLayout(card)
        result_layout.setContentsMargins(16, 14, 16, 14)
        result_layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(self.result_title, 1)
        top.addWidget(QLabel("Layer", objectName="Muted"))
        top.addWidget(self.layer_box)
        result_layout.addLayout(top)
        result_layout.addWidget(self.result_info)
        # While an analysis runs, a rotating Earth takes the map's place.
        self.run_loader = EarthLoader("Running analysis…", "Starting…", size=120)
        self.run_stack = QStackedWidget()
        self.run_stack.addWidget(self.map_area)     # 0: the result map
        self.run_stack.addWidget(self.run_loader)   # 1: the loader
        result_layout.addWidget(self.run_stack, 1)
        self.filmstrip = RunFilmstrip()
        self.filmstrip.open_requested.connect(self.open_in_viewer_requested)
        self._film_for = ""                                  # the project the filmstrip shows
        self._film_pictures: dict[str, object] = {}          # drawn pictures, by GeoTIFF: drawn once
        result_layout.addWidget(_section("Saved runs"))
        result_layout.addWidget(self.filmstrip)

        # ---- beside the map: its numbers, its symbology, and what to do with the result
        side = QFrame(objectName="ResultCard")
        side.setFixedWidth(SIDE_WIDTH)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 12, 14, 14)
        side_layout.setSpacing(8)
        side_layout.addWidget(_section("Numbers"))
        side_layout.addWidget(self.metrics_table)
        side_layout.addWidget(self.sym_panel, 1)
        side_layout.addWidget(self.save_state)
        # The buttons wrap onto a second line when the column is narrow, instead of being clipped.
        buttons = FlowLayout(spacing=6)
        for button in (self.save_button, self.explain_button, self.viewer_button, self.map_button,
                       self.folder_button):
            buttons.addWidget(button)
        side_layout.addLayout(buttons)

        # ---- setup: a slim rail; its drawer is the steps panel (open until there is a result)
        self._panel = panel
        self._result_card = card
        self._side = side
        rail = QFrame(objectName="AnalysisRail")
        rail.setFixedWidth(RAIL_WIDTH)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(6, 10, 6, 10)
        rail_layout.setSpacing(8)
        self.rail_buttons: dict[str, QPushButton] = {}
        for key, text, tip in (("data", "Data", "Choose the dataset (step 1)"),
                               ("type", "Type", "Choose the kind of analysis (step 2)"),
                               ("steps", "Steps", "Choose the processes and their parameters (step 3)")):
            button = QPushButton(text, objectName="RailButton")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.open_setup_at(k))
            rail_layout.addWidget(button)
            self.rail_buttons[key] = button
        self.rail_run = QPushButton("Run", objectName="PrimaryButton")
        self.rail_run.setToolTip("Run the analysis (the same as Run analysis in the setup)")
        self.rail_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rail_run.clicked.connect(self.run)
        rail_layout.addWidget(self.rail_run)
        rail_layout.addStretch(1)

        body = QHBoxLayout()
        body.setSpacing(RESULT_SPACING)
        body.addWidget(rail)
        body.addWidget(panel)
        body.addWidget(card, 1)
        body.addWidget(side)
        self._page_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.banner)
        layout.addLayout(body, 1)
        self.set_setup_open(True)  # nothing to show yet: the steps lead until the first result
        self._arrange_results()

        for button in (self.refresh_button, self.browse_button, self.run_button, self.viewer_button,
                       self.map_button, self.folder_button, self.save_button, self.explain_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        for widget in (self.refresh_button, self.browse_button, self.dataset_note, self.category_note,
                       self.compare_note):
            _shrinkable(widget)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(PROGRESS_POLL_MS)
        self._progress_timer.timeout.connect(self._tick_progress)

        self.dataset_list.currentRowChanged.connect(self._on_dataset_row)
        self.refresh_button.clicked.connect(self.refresh_datasets)
        self.browse_button.clicked.connect(self.browse)
        self.picker.changed.connect(self._on_processes_changed)
        self.save_button.clicked.connect(self.save_result)
        self.use_gpu.toggled.connect(self._on_use_gpu)
        self.run_button.clicked.connect(self.run)
        self.layer_box.currentIndexChanged.connect(self.show_layer)
        self.viewer_button.clicked.connect(self._open_in_viewer)
        self.map_button.clicked.connect(self.show_on_map)
        self.folder_button.clicked.connect(self.open_folder)
        self.explain_button.clicked.connect(self.explain)
        self._show_processes(None)
        self._set_result_buttons(False)
        self._show_save_state()
        self._update_run_button()

    # ------------------------------------------------------------- responsive layout
    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._arrange_results()

    def _arrange_results(self) -> None:
        """Fit the page to its size: compact header and margins on short pages, a narrower drawer
        on narrow ones."""
        # Layout 3's division strip and open run log take part of the window; they do not make the page short.
        short = self.height() < SHORT_PAGE - (fieldbook.CHROME_HEIGHT if fieldbook.active() else 0)
        margins = (16, 10, 16, 10) if short else (24, 20, 24, 20)
        self._page_layout.setContentsMargins(*margins)
        self.subtitle.setVisible(not short)
        self._panel.setFixedWidth(PANEL_WIDTH if self.width() >= WIDE_PAGE else PANEL_WIDTH_COMPACT)

    # ------------------------------------------------------------- setup drawer
    def set_setup_open(self, open_: bool) -> None:
        """Show or fold the steps drawer. It folds when a result arrives, so the result leads."""
        self._panel.setVisible(open_)
        if not open_:
            for button in self.rail_buttons.values():
                button.setChecked(False)

    def setup_is_open(self) -> bool:
        return not self._panel.isHidden()

    def open_setup_at(self, key: str) -> None:
        """A rail button: open the drawer at its step, or fold the drawer if that step is already shown."""
        if self.setup_is_open() and self.rail_buttons[key].isChecked() is False:
            self.set_setup_open(False)
            return
        self.set_setup_open(True)
        for name, button in self.rail_buttons.items():
            button.setChecked(name == key)
        widget = self._step_widgets[key]
        QTimer.singleShot(0, lambda: self._panel_scroll.ensureWidgetVisible(widget, 0, 12))

    # ------------------------------------------------------------- filmstrip of saved runs
    def _load_filmstrip(self) -> None:
        """List the open project's saved results in the background, then draw their pictures."""
        project = current_project(self._facade)
        if project is None:
            self._film_for = ""
            self.filmstrip.set_runs([])
            return
        self._film_for = project.id
        run_task(self, self._facade.list_saved_results,
                 on_success=lambda results, wanted=project.id: self._on_film_results(wanted, results),
                 on_error=lambda _exc: self.filmstrip.set_runs([]))

    def _on_film_results(self, project_id: str, results) -> None:
        if project_id != self._film_for:
            return  # another project was opened meanwhile
        shown = list(results)[:FILM_SHOWN]
        runs = []
        for result in shown:
            figure = next(iter(result.metrics.items()), None)
            caption = ", ".join(result.processes) or result.category
            if figure is not None:
                caption += f" {format_value(figure[1])}"
            runs.append((result.output_path, caption,
                         f"{result.category}: {', '.join(result.processes)}\n{Path(result.output_path).name}"))
        self.filmstrip.set_runs(runs)
        for result in shown:
            path = result.output_path
            if path in self._film_pictures:
                self.filmstrip.set_picture(path, self._film_pictures[path])
                continue
            run_task(self, self._facade.get_map_layers, result, FILM_PICTURE,
                     on_success=lambda layers, path=path: self._on_film_picture(path, layers),
                     on_error=lambda _exc, path=path: self._on_film_picture(path, []))

    def _on_film_picture(self, path: str, layers) -> None:
        image = rgba_to_image(layers[0].data) if layers else None
        self._film_pictures[path] = image
        self.filmstrip.set_picture(path, image)

    # ------------------------------------------------------------- loading
    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.refresh_datasets()
            self.find_device()

    def refresh_datasets(self) -> None:
        """The open project's finished downloads (newest first), then GeoTIFFs opened from disk."""
        has_project = current_project(self._facade) is not None
        for widget in (self.refresh_button, self.browse_button):
            widget.setEnabled(has_project)
        if not has_project:
            self.opened = []
            self.set_datasets([])
            self.dataset_note.setText(NO_PROJECT)
            return
        try:
            downloads = list(self._facade.list_analysis_datasets())
        except GeeAssistError as exc:
            self.banner.show_error(str(exc))
            downloads = []
        known = {dataset.path for dataset in downloads}
        self.set_datasets(downloads + [d for d in self.opened if d.path not in known])
        self._load_filmstrip()

    def set_datasets(self, datasets: list[DatasetDTO]) -> None:
        previous = self.dataset.path if self.dataset else None
        self.datasets = datasets
        self.dataset_list.blockSignals(True)
        self.dataset_list.clear()
        for dataset in datasets:
            item = QListWidgetItem(f"{dataset_title(dataset)}\n{dataset.name or Path(dataset.path).stem}"
                                   f"  ·  {format_size(dataset.size_bytes) if dataset.size_bytes else ''}".rstrip(" ·"))
            item.setToolTip(dataset.path)
            self.dataset_list.addItem(item)
        self.dataset_list.blockSignals(False)
        if not datasets:
            self.dataset_note.setText("No finished downloads yet. Download a dataset from Query Input, or open a "
                                      "GeoTIFF from your computer.")
        else:
            self.dataset_note.setText(f"{len(datasets)} dataset{'s' if len(datasets) != 1 else ''} ready.")
        paths = [dataset.path for dataset in datasets]
        if previous in paths:
            self.dataset_list.setCurrentRow(paths.index(previous))
        elif datasets:
            self.dataset_list.setCurrentRow(0)
        else:
            self.choose_dataset(None)

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open GeoTIFF to analyse", downloads_folder(self._facade),
                                              "GeoTIFF (*.tif *.tiff);;All files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        """Add any GeoTIFF on the computer to the list and choose it (read in the background)."""
        self.banner.show_info("Reading the file…")
        run_task(self, self._facade.describe_dataset, path, on_success=self._on_file_described,
                 on_error=self._show_error)

    def _on_file_described(self, dataset: DatasetDTO) -> None:
        self.banner.clear()
        self.opened = [d for d in self.opened if d.path != dataset.path] + [dataset]
        datasets = [d for d in self.datasets if d.path != dataset.path] + [dataset]
        self.set_datasets(datasets)
        self.dataset_list.setCurrentRow(len(datasets) - 1)

    # ------------------------------------------------------------- choosing
    def _on_dataset_row(self, row: int) -> None:
        self.choose_dataset(self.datasets[row] if 0 <= row < len(self.datasets) else None)

    def choose_dataset(self, dataset: DatasetDTO | None) -> None:
        self.dataset = dataset
        self.options = []
        self._fill_categories()
        self._fill_compare()
        if dataset is None:
            return
        self.category_note.setText("Checking which analyses this dataset can run…")
        run_task(self, self._facade.get_available_analyses, dataset,
                 on_success=lambda options, path=dataset.path: self._on_options(path, options),
                 on_error=self._show_error)

    def _on_options(self, path: str, options: list[AnalysisOptionDTO]) -> None:
        if self.dataset is None or self.dataset.path != path:
            return  # another dataset was chosen meanwhile
        self.options = list(options)
        self._fill_categories()
        available = [option for option in self.options if option.available]
        self.category_note.setText(
            f"{len(available)} of {len(self.options)} analyses can run on this dataset."
            if self.options else "")
        keep = next((o for o in available if o.category == self.category), None)
        self.choose_category((keep or (available[0] if available else None)).category if available else "")

    def _fill_categories(self) -> None:
        """One tile per analysis (water, vegetation, LST, LULC), two to a row."""
        while self.tiles_area.count():
            item = self.tiles_area.takeAt(0)
            row = item.layout()
            while row is not None and row.count():
                widget = row.takeAt(0).widget()
                if widget is not None:
                    widget.deleteLater()
        self.analysis_tiles = {}
        row = None
        for index, option in enumerate(self.options):
            if index % 2 == 0:
                row = QHBoxLayout()
                row.setSpacing(6)
                self.tiles_area.addLayout(row)
            tile = AnalysisTile(option)
            tile.clicked.connect(lambda _=False, category=option.category: self.choose_category(category))
            row.addWidget(tile, 1)
            self.analysis_tiles[option.category] = tile
        if not self.options:
            self.category = ""
            self._show_processes(None)

    def choose_category(self, category: str) -> None:
        self.category = category
        for name, tile in self.analysis_tiles.items():
            tile.setChecked(name == category)
        self._show_processes(self.option(category))

    def option(self, category: str) -> AnalysisOptionDTO | None:
        return next((option for option in self.options if option.category == category), None)

    def _show_processes(self, option: AnalysisOptionDTO | None) -> None:
        formulas = {formula.key: formula for formula in self._formulas()} if option is not None else {}
        self.picker.set_option(option, formulas)

    def _formulas(self):
        if not hasattr(self, "_formula_cache"):
            try:
                self._formula_cache = list(self._facade.list_formulas())
            except GeeAssistError:
                self._formula_cache = []
        return self._formula_cache

    def chosen_processes(self) -> list[str]:
        return self.picker.selected()

    def _chosen_options(self) -> list[ProcessOptionDTO]:
        return self.picker.selected_options()

    def _on_processes_changed(self, *_args) -> None:
        self._fill_params()
        needs_compare = any(p.periods > 1 for p in self._chosen_options())
        for widget in (self.compare_title, self.compare_note, self.compare_list):
            widget.setVisible(needs_compare)
        self._update_run_button()

    def _fill_params(self) -> None:
        values = {key: box.value() for key, box in self.param_boxes.items()}
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self.param_boxes = {}
        wanted: list[str] = []
        for process in self._chosen_options():
            for name in process.params:
                if name == "water_threshold" and self.dataset is not None and self.dataset.satellite == "Sentinel-1":
                    name = "sar_water_db"  # radar: the backscatter threshold decides
                if name in PARAMETERS and name not in wanted:
                    wanted.append(name)
        for name in wanted:
            label, default, low, high, step, tip = PARAMETERS[name]
            box = QDoubleSpinBox()
            box.setRange(low, high)
            box.setSingleStep(step)
            box.setDecimals(2)
            box.setValue(values.get(name, default))
            box.setToolTip(tip)
            name_label = QLabel(label, objectName="Muted")
            name_label.setWordWrap(True)
            self.params_form.addRow(_shrinkable(name_label), box)
            self.param_boxes[name] = box
        self.params_title.setVisible(bool(wanted))

    def _fill_compare(self) -> None:
        self.compare_list.clear()
        for dataset in self.datasets:
            if self.dataset is not None and dataset.path == self.dataset.path:
                continue
            item = QListWidgetItem(f"{dataset_title(dataset)}\n{dataset.name or Path(dataset.path).stem}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, dataset.path)
            item.setToolTip(dataset.path)
            self.compare_list.addItem(item)
        if not self.compare_list.count():
            item = QListWidgetItem("No other dataset yet: download the same place for another date.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.compare_list.addItem(item)

    def compare_datasets(self) -> list[DatasetDTO]:
        paths = {self.compare_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.compare_list.count())
                 if self.compare_list.item(i).checkState() == Qt.CheckState.Checked}
        return [dataset for dataset in self.datasets if dataset.path in paths]

    def set_compare(self, paths: list[str]) -> None:
        for i in range(self.compare_list.count()):
            item = self.compare_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) is not None:
                item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in paths
                                   else Qt.CheckState.Unchecked)

    # ------------------------------------------------------------- device
    def find_device(self) -> None:
        run_task(self, self._facade.get_compute_device, True, on_success=self._on_device,
                 on_error=lambda exc: self.device_label.setText("Runs on the CPU"))

    def _on_device(self, device: ComputeDeviceDTO) -> None:
        first_time = self.device is None
        self.device = device
        self.device_label.setText(device_text(device))
        cards = "\n".join(f"• {gpu.name} ({gpu.kind})" for gpu in device.gpus) or "none found"
        self.device_detail.setText(device.reason)
        tip = f"{device.reason}\n\nGraphics cards on this computer:\n{cards}"
        for widget in (self.device_label, self.device_detail):
            widget.setToolTip(tip)
        if first_time:
            usable = device.uses_gpu
            self.use_gpu.blockSignals(True)
            self.use_gpu.setChecked(usable)
            self.use_gpu.setEnabled(usable)
            self.use_gpu.blockSignals(False)
            self.use_gpu.setVisible(bool(device.dedicated_gpus))

    def _on_use_gpu(self, on: bool) -> None:
        run_task(self, self._facade.get_compute_device, on, on_success=self._on_device_changed)

    def _on_device_changed(self, device: ComputeDeviceDTO) -> None:
        self.device = device
        self.device_label.setText(device_text(device))
        self.device_detail.setText(device.reason)
        self.use_gpu.setEnabled(True)  # the GPU worked once: it can be switched back on

    # ------------------------------------------------------------- running
    def project_changed(self) -> None:
        """Another project was opened, or it was closed: show its datasets (files opened from disk are dropped)."""
        self.opened = []
        if self._loaded:
            self.refresh_datasets()

    def _update_run_button(self) -> None:
        ready = (self.dataset is not None and bool(self.chosen_processes()) and not self.running
                 and current_project(self._facade) is not None)
        self.run_button.setEnabled(ready)
        self.run_button.setText("Running…" if self.running else "Run analysis")
        if hasattr(self, "rail_run"):  # the rail's Run mirrors the setup's Run analysis
            self.rail_run.setEnabled(ready)

    def build_request(self) -> AnalysisRequestDTO:
        params = {name: box.value() for name, box in self.param_boxes.items()}
        return AnalysisRequestDTO(self.category, self.chosen_processes(), params, self.compare_datasets(),
                                  use_gpu=self.use_gpu.isChecked() and self.use_gpu.isEnabled())

    def run(self) -> None:
        if self.dataset is None or self.running:
            return
        request = self.build_request()
        if not request.processes:
            self.banner.show_error("Choose at least one process.")
            return
        needs = max((p.periods for p in self._chosen_options()), default=1)
        if needs > 1 and not request.compare_with:
            self.banner.show_error("A before / after process is chosen: tick an earlier dataset under "
                                   "“Compare with”.")
            return
        self.running = True
        self._progress = 0.0
        self.progress.setValue(0)
        self.progress.show()
        self.run_loader.set_text("Running analysis…", "Starting…")
        self.run_stack.setCurrentWidget(self.run_loader)
        self._progress_timer.start()
        self._update_run_button()
        where = "GPU" if request.use_gpu and self.device is not None and self.device.uses_gpu else "CPU"
        self.banner.show_info(f"Running {', '.join(request.processes)} on the {where}…")
        run_task(self, self._facade.run_analysis, self.dataset, request, self._set_progress,
                 on_success=self._on_result, on_error=self._on_run_failed)

    def _set_progress(self, fraction: float) -> None:
        self._progress = fraction  # called from the worker thread; the timer shows it

    def _tick_progress(self) -> None:
        """On the UI thread (timer): mirror the worker's progress on the bar and the loader."""
        percent = round(self._progress * 100)
        self.progress.setValue(percent)
        self.run_loader.set_text("Running analysis…", f"{percent}% complete")

    def _finish_run(self) -> None:
        self.running = False
        self._progress_timer.stop()
        self.progress.hide()
        self.run_stack.setCurrentWidget(self.map_area)
        self._update_run_button()

    def _on_run_failed(self, exc: Exception) -> None:
        self._finish_run()
        self._show_error(exc)

    def _on_result(self, result: ResultDTO) -> None:
        self._finish_run()
        self.set_setup_open(False)  # the result leads; the rail reopens the steps
        if self.result is not None and not self.result.saved:
            self._facade.discard_analysis_result(self.result)  # replaced before it was saved
        self.result = result
        self.analysis_finished.emit(result)
        self._show_save_state()
        self.result_title.setText(f"{result.category}: {', '.join(result.processes)}")
        parts = [f"{result.device}", f"{result.seconds:.2f} s", Path(result.output_path).name]
        self.result_info.setText("  ·  ".join(parts) + ("\n" + " ".join(result.notes) if result.notes else ""))
        self._fill_metrics(result.metrics)
        self.banner.show_success(f"Done in {result.seconds:.1f} s on the {result.device}. Drawing the layers…")
        run_task(self, self._facade.get_map_layers, result, on_success=self._on_layers, on_error=self._show_error)

    def _on_layers(self, layers: list[MapLayerDTO]) -> None:
        self.layers = list(layers)
        self.layer_box.blockSignals(True)
        self.layer_box.clear()
        for layer in self.layers:
            self.layer_box.addItem(layer.name, layer.id)
        self.layer_box.blockSignals(False)
        self._set_result_buttons(bool(self.layers))
        if self.layers:
            self.show_layer(0)
        self.banner.clear()

    def show_layer(self, index: int) -> None:
        if not 0 <= index < len(self.layers):
            return
        layer = self.layers[index]
        self._current_layer = layer
        self.layer_box.blockSignals(True)
        self.layer_box.setCurrentIndex(index)
        self.layer_box.blockSignals(False)
        self.sym_panel.set_layer(layer, self._run_info())
        self.map_area.set_image(rgba_to_image(layer.data), layer.bounds, layer.width, keep_view=True)
        self.map_area.set_opacity(1.0)
        self._update_overlay_legend(layer)

    def _run_info(self) -> dict:
        result, dataset = self.result, self.dataset
        return {
            "device": result.device if result else "",
            "duration": f"{result.seconds:.2f} s" if result else "",
            "dataset": (dataset.name or dataset.satellite) if dataset else "",
        }

    def _recolor(self) -> None:
        """Redraw the current layer from the symbology panel's settings (ramp, stretch, classes…)."""
        rgba = self.sym_panel.current_rgba()
        if rgba is not None:
            self.canvas.set_image(rgba_to_image(rgba), keep_view=True)
        if self._current_layer is not None:
            self._update_overlay_legend(self._current_layer)

    def _update_overlay_legend(self, layer: MapLayerDTO) -> None:
        if layer.kind == "scale":
            colours, low, high = self.sym_panel.scale_legend()
            self.map_area.show_legend_scale(layer.name, colours, low, high)
        else:
            rows = self.sym_panel.legend_rows()
            self.map_area.show_legend_classes(layer.legend.title or "Legend", rows)

    def _fill_metrics(self, metrics: dict[str, float]) -> None:
        self.metrics_table.setRowCount(0)
        for name, value in metrics.items():
            row = self.metrics_table.rowCount()
            self.metrics_table.insertRow(row)
            self.metrics_table.setItem(row, 0, QTableWidgetItem(name))
            item = QTableWidgetItem(format_value(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.metrics_table.setItem(row, 1, item)

    def _set_result_buttons(self, ready: bool) -> None:
        for button in (self.viewer_button, self.map_button, self.save_button, self.explain_button):
            button.setEnabled(ready)
        self.layer_box.setEnabled(ready)
        self.folder_button.setEnabled(ready and self.result is not None and self.result.saved)

    # ------------------------------------------------------------- saving
    def suggested_save_path(self) -> str:
        """Where "Save result" puts the result: the open project's analysis folder, under a name not taken yet."""
        if self.result is None:
            return ""
        target = Path(analysis_folder(self._facade)) / Path(self.result.output_path).name
        number = 2
        while target.exists():  # never overwrite an earlier result
            target = target.with_name(f"{Path(self.result.output_path).stem}_{number}{target.suffix}")
            number += 1
        return str(target)

    def save_result(self) -> None:
        """Save the result in the open project's analysis folder (nothing is kept unless the user does this)."""
        if self.result is None:
            return
        if current_project(self._facade) is None:
            self.banner.show_error("Open a project to save the result: it is saved in the project's analysis folder.")
            return
        self.save_to(self.suggested_save_path())

    def save_to(self, path: str) -> None:
        if self.result is None:
            return
        self.save_button.setEnabled(False)
        run_task(self, self._facade.save_analysis_result, self.result, path, on_success=self._on_saved,
                 on_error=self._on_save_failed)

    def _on_saved(self, result: ResultDTO) -> None:
        self.result = result
        self.save_button.setEnabled(True)
        self.folder_button.setEnabled(True)
        self._show_save_state()
        self.banner.show_success(f"Saved to {result.output_path}")
        self._load_filmstrip()  # the new saved result joins the filmstrip

    def _on_save_failed(self, exc: Exception) -> None:
        self.save_button.setEnabled(True)
        self._show_error(exc)

    def _show_save_state(self) -> None:
        result = self.result
        if result is None:
            self.save_state.setText("")
        elif result.saved:
            self.save_state.setText(f"✓ Saved: {Path(result.output_path).name}")
            self.save_state.setToolTip(result.output_path)
        else:
            self.save_state.setText("Not saved: this result is deleted unless you save it.")
            self.save_state.setToolTip("")
        self.save_state.setProperty("saved", bool(result and result.saved))
        self.save_state.style().unpolish(self.save_state)
        self.save_state.style().polish(self.save_state)

    def discard_unsaved(self) -> None:
        """Delete the result shown if it was not saved (e.g. when the window closes)."""
        if self.result is not None and not self.result.saved:
            self._facade.discard_analysis_result(self.result)

    def set_saved_result(self, result: ResultDTO) -> None:
        """The result shown was saved elsewhere (e.g. before it was sent to Gemini): show it as saved."""
        if self.result is None or self.result.id != result.id or not result.saved:
            return
        self.result = result
        self.folder_button.setEnabled(True)
        self._show_save_state()

    # ------------------------------------------------------------- result actions
    def explain(self) -> None:
        """Ask for an AI explanation of the result (it is saved in the project first)."""
        if self.result is None:
            return
        if current_project(self._facade) is None:
            self.banner.show_error("Open a project to explain the result: it is saved in the project's analysis "
                                   "folder before it is sent to Gemini.")
            return
        self.explain_requested.emit(self.result)

    def _open_in_viewer(self) -> None:
        if self.result is not None:
            self.open_in_viewer_requested.emit(self.result.output_path)

    def open_folder(self) -> None:
        if self.result is not None and self.result.saved:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.result.output_path).parent)))

    def show_on_map(self) -> None:
        index = self.layer_box.currentIndex()
        if self.result is None or not 0 <= index < len(self.layers):
            return
        layer = self.layers[index]
        image = rgba_to_image(layer.data)
        if max(image.width(), image.height()) > MAP_IMAGE_SIZE:
            image = image.scaled(MAP_IMAGE_SIZE, MAP_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        name = self.dataset.name if self.dataset and self.dataset.name else Path(self.result.output_path).stem
        self.show_on_map_requested.emit(bytes(buffer.data()), layer.bounds, f"{name} · {layer.name}")

    def _show_error(self, exc: Exception) -> None:
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else
                               f"The analysis could not be completed: {exc}")
