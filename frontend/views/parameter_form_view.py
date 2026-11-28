"""UC-03 Fill Parameter Form + UC-04 Import GeoJSON."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.config import (
    ANALYSIS_CATEGORIES,
    BYTES_PER_PIXEL,
    COMPOSITE_METHODS,
    CRS_OPTIONS,
    DEFAULT_DOWNLOAD_DIR,
    GEE_MAX_GRID_DIMENSION,
    GEE_MAX_REQUEST_BYTES,
    GEE_REQUEST_BYTES_PER_PIXEL,
    DatasetInfo,
    datasets_by_category,
    get_dataset,
)
from backend.dto import FormDTO, PlaceDTO, ValidationDTO
from backend.config.limits import MAX_QUERY_LENGTH
from backend.exceptions import GeeAssistError
from frontend import form_theme as theme
from frontend import layout_mode, palette, theming
from frontend.aoi_geometry import (
    bbox_of,
    estimate_download,
    bbox_polygon,
    circle_polygon,
    format_bytes,
    format_distance,
    polygon_from_geojson,
    vertex_count,
)
from frontend.widgets.aoi_map_widget import AoiMapWidget
from frontend.widgets.query_assistant import QueryAssistant
from frontend.widgets.form_parts import (
    CheckComboBox,
    StatusBanner,
    divider,
    field_row,
    hint_label,
    labelled,
    pad_spin_text,
    section_card,
    set_invalid,
)
from frontend.workers.task_worker import run_task

AOI_FILE, AOI_DRAW = 0, 1
NO_SHAPE_TEXT = "No shape drawn yet."
NO_FILE_TEXT = "No file imported."


# ---------------------------------------------------------------------- helpers
def _qdate(value) -> QDate:
    return QDate(value.year, value.month, value.day)


def _polygon_vertices(aoi: str) -> list[tuple[float, float]]:
    """The (lat, lon) points of an AOI's outer ring, with the repeated closing point dropped."""
    if not aoi:
        return []
    try:
        geometry = json.loads(aoi)
    except (ValueError, TypeError):
        return []
    kind = geometry.get("type")
    if kind == "Polygon":
        ring = geometry.get("coordinates", [[]])[0]
    elif kind == "MultiPolygon":
        ring = geometry.get("coordinates", [[[]]])[0][0]
    else:
        return []
    points = [(float(c[1]), float(c[0])) for c in ring if len(c) >= 2]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def _segment_button(text: str, position: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("SegmentButton")
    button.setProperty("segment", position)
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


NO_PROJECT_FOLDER = "Create or open a project: downloads are saved in its downloads folder"

# Fields that must be filled before the parameters can be submitted, in the order they are listed.
REQUIRED_FIELDS = (
    ("aoi", "Area of interest"),
    ("dataset", "Dataset"),
    ("bands", "Bands"),
    ("output_dir", "Project folder"),
)
# Modern layout: the tab each field is on (Area, Data, Time, Output).
TAB_NAMES = ("Area", "Data", "Time", "Output")
# Studio layout: the heading and one-line hint shown above each section's fields.
STUDIO_STEPS = (
    ("Area of interest", "Pick a place, draw a shape or import a boundary to analyse."),
    ("Dataset & bands", "Choose the satellite collection, bands and how scenes combine."),
    ("Time range", "Images acquired between these dates are used."),
    ("Output", "The projection, and where the GeoTIFF is saved."),
)
FIELD_TABS = {"aoi": 0, "dataset": 1, "bands": 1, "scale": 1, "max_cloud_cover": 1, "composite": 1,
              "dates": 2, "crs": 3, "output_dir": 3}
FIELD_ORDER = ("aoi", "dataset", "bands", "scale", "max_cloud_cover", "composite", "dates", "crs", "output_dir")

# Responsive layout
MODERN_PANEL_WIDTH = 440
MODERN_PANEL_MIN_WIDTH = 340
SHORT_PAGE = 600        # below this height the modern panel header drops its subtitle
NARROW_PAGE = 900       # below this width the classical Time and Output cards stack
def _needed() -> str:
    """The "still to fill" colour: amber, or a three-colour theme's accent (it keeps to three colours)."""
    if palette.THEME in palette.THREE_COLOUR_THEMES:
        return palette.ACTIVE["LEAF"]
    return "#F5B83D" if layout_mode.is_modern() or palette.IS_DARK else "#B7791F"


def _done() -> str:
    return theme.M_ACCENT if layout_mode.is_modern() else theme.SUCCESS


class ParameterFormView(QWidget):
    """Collects every parameter GEE needs to fetch data, validates and keeps it."""

    request_kept = pyqtSignal(object)  # FormDTO

    def __init__(self, facade: IBusinessFacade, parent=None):
        super().__init__(parent)
        self._facade = facade
        self._project_downloads = ""
        self._analysis: tuple[str, list[str]] = ("", [])  # set only by gkonsol; the page is download-only  # the open project's downloads folder: every download goes there
        self._imported_aoi: str = ""
        self._imported_name: str = ""
        self._drawn_aoi: str = ""  # GeoJSON of the rectangle / circle / polygon on the map
        self._drawn_name: str = ""
        self._bbox_snapshot: tuple[float, float, float, float] | None = None  # spins' value, to tell real edits apart
        self._places: list[PlaceDTO] = []  # matches of the last place search
        self._place_search_id = 0          # ignores answers to searches that were superseded
        self._error_labels: dict[str, QLabel] = {}
        self._error_targets: dict[str, tuple[QWidget, ...]] = {}

        self.setObjectName("ParameterForm")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._modern = layout_mode.is_modern()
        self._studio = layout_mode.is_studio()
        # Both the modern and studio layouts group the parameters into tabbed/stacked "pages"
        # (vs. the classical scrolling cards), so the field builders share that branch.
        self._paneled = self._modern or self._studio

        def _build_stylesheet() -> str:
            if self._modern:
                extra = theme.MODERN_FORM_STYLESHEET
            elif self._studio:
                extra = theme.STUDIO_FORM_STYLESHEET
            else:
                extra = ""
            return theme.FORM_STYLESHEET + extra

        theming.styled(self, _build_stylesheet)  # re-themes live on a theme change
        theming.on_theme_changed(self._update_required)  # its "Still needed" line is coloured rich text

        # ---- action widgets, shared by both layouts
        self.estimate_label = hint_label()  # download size; placed by whichever layout is built
        self.status_banner = StatusBanner()
        # "Still needed: Area of interest · Bands": each item is a link to that field.
        self.required_label = QLabel()
        self.required_label.setObjectName("RequiredList")
        self.required_label.setTextFormat(Qt.TextFormat.RichText)
        self.required_label.setWordWrap(True)
        self.required_label.linkActivated.connect(self.go_to_field)
        self._field_errors: set[str] = set()   # fields whose last validation failed
        self._modern_tab_buttons: list[QPushButton] = []
        self.reset_button = QPushButton("Reset")
        self.reset_button.setObjectName("SecondaryButton")
        self.submit_button = QPushButton("Submit Parameters")
        self.submit_button.setObjectName("PrimaryButton")
        self.submit_button.setDefault(True)
        for button in (self.reset_button, self.submit_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(40)

        # The same field widgets, arranged two ways: the classical scrolling cards,
        # or the modern map-first panel with the parameters grouped under tabs.
        if self._modern:
            self._assemble_modern()
        elif self._studio:
            self._assemble_studio()
        else:
            self._assemble_classic()

        self.dataset_combo.currentIndexChanged.connect(self._on_dataset_changed)
        self._aoi_mode.idClicked.connect(self._on_aoi_mode_changed)
        self.import_button.clicked.connect(self._on_import_geojson)
        self.map_widget.bbox_drawn.connect(self._on_map_bbox_drawn)
        self.map_widget.circle_drawn.connect(self._on_map_circle_drawn)
        self.map_widget.polygon_drawn.connect(self._on_map_polygon_drawn)
        self.map_widget.shape_cleared.connect(self._on_map_shape_cleared)
        self.place_edit.returnPressed.connect(self._on_place_search)
        self.place_search_button.clicked.connect(self._on_place_search)
        self.place_results_combo.activated.connect(self._on_place_chosen)
        for spin in self._bbox_spins:
            spin.editingFinished.connect(self._on_bbox_typed)
        pad_spin_text(self.scale_spin, self.cloud_spin, *self._bbox_spins)
        self.browse_button.clicked.connect(self._on_browse_output)
        self.output_dir_edit.textEdited.connect(lambda _: self._set_field_error("output_dir", ""))
        self.bands_combo.selection_changed.connect(self._update_estimate)
        self.scale_spin.valueChanged.connect(self._update_estimate)
        self.reset_button.clicked.connect(self.reset)
        self.dataset_combo.currentIndexChanged.connect(self._update_required)
        self.output_dir_edit.textChanged.connect(self._update_required)
        self._aoi_mode.idClicked.connect(self._update_required)
        self.submit_button.clicked.connect(self._on_submit)

        # Natural-language assistant (UC-02): fills this form via Gemini. The
        # main window places it in the side panel, under the kept requests.
        self.assistant = QueryAssistant(MAX_QUERY_LENGTH)
        self.assistant.submitted.connect(self._on_query_submitted)

        self.reset()
        self._update_required()

    # ----------------------------------------------------------- assembly (classical)
    def _assemble_classic(self) -> None:
        """The original layout: a page heading over scrolling cards, with a bottom action bar."""
        title = QLabel("Parameter Form")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Tell Google Earth Engine what to fetch: the dataset, the area, the time range and the analysis.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)

        # ---- time range and output share one row
        time_and_output = QHBoxLayout()
        self._time_output_row = time_and_output   # stacks on narrow pages (see resizeEvent)
        time_and_output.setSpacing(14)
        time_and_output.addWidget(self._build_time_group(), 2)
        time_and_output.addWidget(self._build_output_group(), 3)

        content = QWidget()
        content.setObjectName("ParameterFormContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 18, 22, 22)
        content_layout.setSpacing(14)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addSpacing(2)
        content_layout.addWidget(self._build_dataset_group())
        content_layout.addWidget(self._build_aoi_group())
        content_layout.addLayout(time_and_output)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        action_bar = QWidget()
        action_bar.setObjectName("FormActionBar")
        action_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        buttons = QHBoxLayout(action_bar)
        buttons.setContentsMargins(22, 10, 22, 10)
        buttons.setSpacing(10)
        messages = QVBoxLayout()
        messages.setSpacing(4)
        messages.addWidget(self.status_banner)
        messages.addWidget(self.required_label)
        buttons.addLayout(messages, 1)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.submit_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(scroll, 1)
        layout.addWidget(action_bar)
        self._form_scroll = scroll

    # ------------------------------------------------------------- assembly (modern)
    def _modern_tab_button(self, text: str, index: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ModernTab")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._modern_stack.setCurrentIndex(index))
        self._modern_tabs.addButton(button, index)
        self._modern_tab_buttons.append(button)
        return button

    @staticmethod
    def _modern_page(card: QFrame) -> QScrollArea:
        """Put a section card on its own scrolling tab page (cards can be taller than the panel)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(card)
        return scroll

    def _modern_area_page(self, toggle_row: QHBoxLayout) -> QWidget:
        """The modern Area tab: the AOI source, place search, extent and a live vertices table."""
        page = QWidget()
        page.setObjectName("ModernAreaPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        # The file / shape summary goes under the toggle: beside it the row is wider than the panel.
        toggle_row.removeWidget(self.aoi_summary_stack)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)
        layout.addWidget(self.aoi_summary_stack)
        layout.addWidget(self.place_box)
        layout.addWidget(self.coords_box)

        head = QHBoxLayout()
        head.setContentsMargins(0, 2, 0, 0)
        vertices_title = QLabel("Vertices")
        vertices_title.setObjectName("FieldLabel")
        self.vertices_count_label = QLabel("No shape yet")
        self.vertices_count_label.setObjectName("FieldHint")
        self.vertices_count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(vertices_title)
        head.addWidget(self.vertices_count_label, 1)
        layout.addLayout(head)

        self.vertices_table = QTableWidget(0, 3)
        self.vertices_table.setObjectName("VerticesTable")
        self.vertices_table.setHorizontalHeaderLabels(["#", "Latitude", "Longitude"])
        self.vertices_table.verticalHeader().setVisible(False)
        self.vertices_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vertices_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.vertices_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vertices_table.setAlternatingRowColors(True)
        self.vertices_table.setMinimumHeight(140)  # the tab scrolls on short screens instead of crushing it
        header = self.vertices_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.vertices_table, 1)
        layout.addWidget(self._error_label("aoi"))
        return page

    def _refresh_vertices(self) -> None:
        """Fill the modern vertices table from the current AOI (draw or imported file)."""
        if getattr(self, "vertices_table", None) is None:
            return
        aoi, _name = self._current_aoi()
        points = _polygon_vertices(aoi)
        self.vertices_table.setRowCount(len(points))
        for row, (lat, lon) in enumerate(points):
            cells = (str(row + 1), f"{lat:.5f}", f"{lon:.5f}")
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                align = Qt.AlignmentFlag.AlignVCenter | (
                    Qt.AlignmentFlag.AlignLeft if column == 0 else Qt.AlignmentFlag.AlignRight
                )
                item.setTextAlignment(align)
                self.vertices_table.setItem(row, column, item)
        if points:
            self.vertices_count_label.setText(f"{len(points):,} point{'s' if len(points) != 1 else ''}")
        else:
            self.vertices_count_label.setText("No shape yet")

    @staticmethod
    def _modern_field_page() -> tuple[QWidget, QVBoxLayout]:
        """An empty modern tab page with standard margins. Returns (page, layout)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        return page, layout

    def _modern_data_page(self) -> QWidget:
        """Modern Data tab: full-width dataset/bands/composite (nothing clipped) + a size estimate."""
        page, layout = self._modern_field_page()
        layout.addWidget(labelled(
            "Dataset", self.dataset_combo, self.dataset_info_label,
            self._error_label("dataset", self.dataset_combo),
        ))
        layout.addWidget(labelled("Bands", self.bands_combo, self._error_label("bands", self.bands_combo)))
        layout.addLayout(field_row(
            labelled("Scale", self.scale_spin, self._error_label("scale", self.scale_spin)),
            labelled("Max cloud cover", self.cloud_spin, self._error_label("max_cloud_cover", self.cloud_spin)),
        ))
        layout.addWidget(labelled("Composite", self.composite_combo, self._error_label("composite", self.composite_combo)))
        layout.addWidget(divider())
        layout.addWidget(labelled("Estimated download size", self.estimate_label))
        layout.addStretch(1)
        return page

    def _modern_time_page(self) -> QWidget:
        """Modern Time tab: start/end dates side by side with the availability hint."""
        page, layout = self._modern_field_page()
        layout.addLayout(field_row(
            labelled("Start date", self.start_date_edit),
            labelled("End date", self.end_date_edit),
        ))
        layout.addWidget(self._error_label("dates", self.start_date_edit, self.end_date_edit))
        layout.addWidget(self.date_hint_label)
        layout.addStretch(1)
        return page

    def _modern_output_page(self, output_error: QLabel) -> QWidget:
        """Modern Output tab: projection only. Downloads always go to the project's folder,
        so the "Save to folder" field is dropped (the field widget is kept, hidden, for logic)."""
        page, layout = self._modern_field_page()
        layout.addWidget(labelled("Projection (CRS)", self.crs_combo, self._error_label("crs", self.crs_combo)))
        layout.addWidget(hint_label(
            "The GeoTIFF is saved to the open project's downloads folder automatically."
        ))
        output_error.setParent(page)  # kept in the widget tree so errors can still surface here
        layout.addWidget(output_error)
        layout.addStretch(1)
        return page

    def _assemble_modern(self) -> None:
        """Map-first layout: a full-height map beside a dark panel whose tabs group the parameters."""

        # Build the same cards as the classical layout; the big map is then pulled out
        # of the Area card so it can fill the left side at all times.
        dataset_card = self._build_dataset_group()
        aoi_card = self._build_aoi_group()
        time_card = self._build_time_group()
        output_card = self._build_output_group()

        # ---- left: the interactive map, always visible
        self.map_widget.setMinimumHeight(0)
        self.map_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        map_panel = QFrame()
        map_panel.setObjectName("ModernMapPanel")
        map_layout = QVBoxLayout(map_panel)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.addWidget(self.map_widget)  # reparents it out of the Area card

        # ---- right: a dark panel with a header, a tab strip and a footer
        header = QLabel("Analysis parameters")
        header.setObjectName("ModernPanelTitle")
        self.modern_subtitle = QLabel("GEE-Assist · Query input")
        self.modern_subtitle.setObjectName("ModernPanelSubtitle")
        self.modern_subtitle.setWordWrap(True)

        self._modern_tabs = QButtonGroup(self)
        self._modern_tabs.setExclusive(True)
        self._modern_stack = QStackedWidget()
        self._modern_stack.addWidget(self._modern_page(aoi_card))      # Area (scrolls on short screens)
        self._modern_stack.addWidget(self._modern_page(dataset_card))  # Data
        self._modern_stack.addWidget(self._modern_page(time_card))     # Time
        self._modern_stack.addWidget(self._modern_page(output_card))   # Output

        tab_strip = QHBoxLayout()
        tab_strip.setSpacing(0)
        for index, name in enumerate(TAB_NAMES):
            tab_strip.addWidget(self._modern_tab_button(name, index))
        self._modern_tabs.button(0).setChecked(True)

        footer = QWidget()
        footer.setObjectName("ModernFooter")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 12, 18, 16)
        footer_layout.setSpacing(10)
        footer_layout.addWidget(self.status_banner)
        footer_layout.addWidget(self.required_label)
        footer_buttons = QHBoxLayout()
        footer_buttons.setSpacing(10)
        footer_buttons.addWidget(self.reset_button)
        footer_buttons.addWidget(self.submit_button, 1)
        footer_layout.addLayout(footer_buttons)

        panel = QFrame()
        panel.setObjectName("ModernPanel")
        panel.setFixedWidth(MODERN_PANEL_WIDTH)
        self._modern_panel = panel
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        head_box = QVBoxLayout()
        head_box.setContentsMargins(18, 18, 18, 10)
        head_box.setSpacing(3)
        head_box.addWidget(header)
        head_box.addWidget(self.modern_subtitle)
        panel_layout.addLayout(head_box)
        strip_box = QHBoxLayout()
        strip_box.setContentsMargins(18, 0, 18, 10)
        strip_box.addLayout(tab_strip)
        panel_layout.addLayout(strip_box)
        panel_layout.addWidget(self._modern_stack, 1)
        panel_layout.addWidget(footer)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(map_panel, 1)
        root.addWidget(panel, 0)

    # ------------------------------------------------------------- assembly (studio)
    def _studio_nav_button(self, text: str, index: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("StudioNav")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._show_studio_step(index))
        self._modern_tabs.addButton(button, index)
        self._modern_tab_buttons.append(button)
        return button

    def _set_studio_step_text(self, index: int) -> None:
        title, hint = STUDIO_STEPS[index]
        self._studio_step_title.setText(title)
        self._studio_step_hint.setText(hint)

    def _show_studio_step(self, index: int) -> None:
        self._modern_stack.setCurrentIndex(index)
        self._set_studio_step_text(index)

    def _assemble_studio(self) -> None:
        """A left nav rail of sections, the chosen section's card in the centre and a
        persistent map-preview card on the right, over the theme's light workspace."""
        # Build the same section pages the modern layout uses (the map is pulled out below).
        dataset_card = self._build_dataset_group()
        aoi_card = self._build_aoi_group()
        time_card = self._build_time_group()
        output_card = self._build_output_group()

        self._modern_tabs = QButtonGroup(self)
        self._modern_tabs.setExclusive(True)
        self._modern_stack = QStackedWidget()
        self._modern_stack.addWidget(self._modern_page(aoi_card))      # Area
        self._modern_stack.addWidget(self._modern_page(dataset_card))  # Data
        self._modern_stack.addWidget(self._modern_page(time_card))     # Time
        self._modern_stack.addWidget(self._modern_page(output_card))   # Output

        # ---- left navigation rail
        rail = QFrame()
        rail.setObjectName("StudioRail")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail.setFixedWidth(196)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(14, 18, 14, 18)
        rail_layout.setSpacing(6)
        kicker = QLabel("Analysis setup")
        kicker.setObjectName("StudioRailKicker")
        rail_layout.addWidget(kicker)
        rail_layout.addSpacing(6)
        for index, name in enumerate(TAB_NAMES):
            rail_layout.addWidget(self._studio_nav_button(name, index))
        rail_layout.addStretch(1)
        self._modern_tabs.button(0).setChecked(True)

        # ---- header (title + live dataset subtitle)
        header = QLabel("Analysis parameters")
        header.setObjectName("StudioTitle")
        self.modern_subtitle = QLabel("GEE-Assist · Query input")
        self.modern_subtitle.setObjectName("StudioSubtitle")
        self.modern_subtitle.setWordWrap(True)

        # ---- centre column: the current step's heading + hint over the stacked card
        self._studio_step_title = QLabel()
        self._studio_step_title.setObjectName("StudioStepTitle")
        self._studio_step_hint = QLabel()
        self._studio_step_hint.setObjectName("FieldHint")
        self._studio_step_hint.setWordWrap(True)
        self._set_studio_step_text(0)
        centre = QVBoxLayout()
        centre.setContentsMargins(0, 0, 0, 0)
        centre.setSpacing(4)
        centre.addWidget(self._studio_step_title)
        centre.addWidget(self._studio_step_hint)
        centre.addSpacing(6)
        centre.addWidget(self._modern_stack, 1)

        # ---- right column: a persistent map preview card
        self.map_widget.setMinimumHeight(0)
        self.map_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        map_card = QFrame()
        map_card.setObjectName("StudioMapCard")
        map_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        map_card_layout = QVBoxLayout(map_card)
        map_card_layout.setContentsMargins(14, 12, 14, 14)
        map_card_layout.setSpacing(8)
        map_caption = QLabel("Map preview · draw or review the area here")
        map_caption.setObjectName("StudioMapCaption")
        map_card_layout.addWidget(map_caption)
        map_card_layout.addWidget(self.map_widget, 1)
        self._studio_map_caption = map_caption

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)
        columns.addLayout(centre, 4)
        columns.addWidget(map_card, 5)

        # ---- footer action bar
        footer = QWidget()
        footer.setObjectName("StudioFooter")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 12)
        footer_layout.setSpacing(10)
        messages = QVBoxLayout()
        messages.setSpacing(4)
        messages.addWidget(self.status_banner)
        messages.addWidget(self.required_label)
        footer_layout.addLayout(messages, 1)
        footer_layout.addWidget(self.reset_button)
        footer_layout.addWidget(self.submit_button)

        main = QVBoxLayout()
        main.setContentsMargins(24, 20, 24, 0)
        main.setSpacing(2)
        main.addWidget(header)
        main.addWidget(self.modern_subtitle)
        main.addSpacing(14)
        main.addLayout(columns, 1)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addLayout(main, 1)
        body.addWidget(footer)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(rail, 0)
        root.addLayout(body, 1)

    # ------------------------------------------------------------------ build
    def _error_label(self, key: str, *targets: QWidget) -> QLabel:
        """Red message under a field; ``targets`` get a red border while it is shown."""
        label = QLabel()
        label.setObjectName("FieldError")
        label.setWordWrap(True)
        label.hide()
        self._error_labels[key] = label
        self._error_targets[key] = targets
        return label

    def _build_dataset_group(self) -> QFrame:
        card, body = section_card("Dataset", "Satellite collection, bands and how the images are combined.")

        # Datasets grouped under non-selectable category headers.
        self.dataset_combo = QComboBox()
        header_font = QFont()
        header_font.setBold(True)
        for category, datasets in datasets_by_category().items():
            self.dataset_combo.addItem(category)
            header = self.dataset_combo.model().item(self.dataset_combo.count() - 1)
            header.setEnabled(False)
            header.setFont(header_font)
            for info in datasets:
                self.dataset_combo.addItem(f"    {info.name}", info.key)
                self.dataset_combo.setItemData(
                    self.dataset_combo.count() - 1, info.collection_id, Qt.ItemDataRole.ToolTipRole
                )
        self.dataset_info_label = hint_label()
        self.dataset_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(1, 100_000)
        self.scale_spin.setSuffix(" m / pixel")

        self.cloud_spin = QSpinBox()
        self.cloud_spin.setRange(0, 100)
        self.cloud_spin.setSuffix(" %")
        self.cloud_spin.setToolTip("Scenes with more cloud cover than this are excluded.")

        self.composite_combo = QComboBox()
        self.composite_combo.addItems(COMPOSITE_METHODS)
        self.composite_combo.setToolTip("How multiple images in the time range are combined into one.")

        self.bands_combo = CheckComboBox(placeholder="No bands selected")

        if self._paneled:
            return self._modern_data_page()

        body.addWidget(labelled(
            "Dataset", self.dataset_combo, self.dataset_info_label,
            self._error_label("dataset", self.dataset_combo),
        ))
        body.addLayout(field_row(
            labelled("Bands", self.bands_combo, self._error_label("bands", self.bands_combo)),
            labelled("Scale", self.scale_spin, self._error_label("scale", self.scale_spin)),
            labelled("Max cloud cover", self.cloud_spin, self._error_label("max_cloud_cover", self.cloud_spin)),
            labelled("Composite", self.composite_combo, self._error_label("composite", self.composite_combo)),
            stretches=(5, 3, 3, 3),
        ))
        return card

    def _build_aoi_group(self) -> QFrame:
        card, body = section_card(
            "Area of Interest",
            "Import a boundary file, search a city or country by name, or draw a rectangle, circle or polygon on the map.",
        )

        # Either a GeoJSON file OR a shape drawn on the map.
        self.aoi_file_toggle = _segment_button("GeoJSON file", "first")
        self.aoi_draw_toggle = _segment_button("Draw on map", "last")
        self._aoi_mode = QButtonGroup(self)
        self._aoi_mode.setExclusive(True)
        self._aoi_mode.addButton(self.aoi_file_toggle, AOI_FILE)
        self._aoi_mode.addButton(self.aoi_draw_toggle, AOI_DRAW)

        # GeoJSON page: import button + summary, on the same row as the toggle
        file_page = QWidget()
        file_layout = QHBoxLayout(file_page)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(12)
        self.import_button = QPushButton("Import GeoJSON…")
        self.import_button.setObjectName("SecondaryButton")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.aoi_file_label = QLabel(NO_FILE_TEXT)
        self.aoi_file_label.setWordWrap(True)
        file_layout.addWidget(self.import_button)
        file_layout.addWidget(self.aoi_file_label, 1)

        # Draw page: shape summary on the toggle row
        draw_page = QWidget()
        draw_layout = QHBoxLayout(draw_page)
        draw_layout.setContentsMargins(0, 0, 0, 0)
        self.shape_label = QLabel(NO_SHAPE_TEXT)
        self.shape_label.setWordWrap(True)
        draw_layout.addWidget(self.shape_label, 1)

        self.aoi_summary_stack = QStackedWidget()
        self.aoi_summary_stack.addWidget(file_page)
        self.aoi_summary_stack.addWidget(draw_page)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(0)
        toggle_row.addWidget(self.aoi_file_toggle)
        toggle_row.addWidget(self.aoi_draw_toggle)
        toggle_row.addSpacing(16)
        toggle_row.addWidget(self.aoi_summary_stack, 1)

        # Place search (draw mode only): the exact boundary of a city / region /
        # country becomes the AOI. Other matches can be picked from a list.
        self.place_edit = QLineEdit()
        self.place_edit.setPlaceholderText("Search a city, region or country, e.g. Lahore, Pakistan")
        self.place_edit.setClearButtonEnabled(True)
        self.place_search_button = QPushButton("Find place")
        self.place_search_button.setObjectName("SecondaryButton")
        self.place_search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.place_results_combo = QComboBox()
        self.place_results_combo.setToolTip("Places with this name: the city, its district, its division… "
                                            "Pick one to use its boundary")
        self.place_results_combo.setMinimumContentsLength(24)
        self.place_results_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.place_results_combo.hide()

        self.place_box = QWidget()
        place_layout = QHBoxLayout(self.place_box)
        place_layout.setContentsMargins(0, 0, 0, 0)
        place_layout.setSpacing(8)
        place_layout.addWidget(self.place_edit, 3)
        place_layout.addWidget(self.place_search_button)
        place_layout.addWidget(self.place_results_combo, 2)

        self.map_widget = AoiMapWidget()
        self.map_widget.setMinimumHeight(360)

        # Bounding-box coordinates (draw mode only): all four on one row.
        def coord_spin(limit: float) -> QDoubleSpinBox:
            spin = QDoubleSpinBox()
            spin.setRange(-limit, limit)
            spin.setDecimals(6)
            spin.setSingleStep(0.01)
            return spin

        self.min_lon_spin, self.max_lon_spin = coord_spin(180), coord_spin(180)
        self.min_lat_spin, self.max_lat_spin = coord_spin(90), coord_spin(90)
        self._bbox_spins = (self.min_lon_spin, self.min_lat_spin, self.max_lon_spin, self.max_lat_spin)

        self.coords_box = QWidget()
        coords_layout = QVBoxLayout(self.coords_box)
        coords_layout.setContentsMargins(0, 0, 0, 0)
        coords_layout.setSpacing(6)
        if self._paneled:
            # Two rows of two: four across does not fit the narrow modern / studio panel.
            coords_layout.addLayout(field_row(
                labelled("West (min lon)", self.min_lon_spin),
                labelled("East (max lon)", self.max_lon_spin),
            ))
            coords_layout.addLayout(field_row(
                labelled("South (min lat)", self.min_lat_spin),
                labelled("North (max lat)", self.max_lat_spin),
            ))
        else:
            coords_layout.addLayout(field_row(
                labelled("West (min lon)", self.min_lon_spin),
                labelled("South (min lat)", self.min_lat_spin),
                labelled("East (max lon)", self.max_lon_spin),
                labelled("North (max lat)", self.max_lat_spin),
            ))
        coords_layout.addWidget(hint_label(
            "Extent of the drawn shape in WGS84 degrees. Typing values replaces the shape with that rectangle."
        ))

        if self._paneled:
            # The map lives in its own panel/card; this tab lists the AOI's own vertices instead,
            # filling the space the map used to take.
            return self._modern_area_page(toggle_row)

        body.addLayout(toggle_row)
        body.addWidget(self.place_box)
        body.addWidget(self.map_widget)
        body.addWidget(self.coords_box)
        body.addWidget(self._error_label("aoi"))
        return card

    def _build_time_group(self) -> QFrame:
        card, body = section_card("Time Range", "Images acquired between these dates are used.")

        def date_edit() -> QDateEdit:
            edit = QDateEdit()
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            return edit

        self.start_date_edit = date_edit()
        self.end_date_edit = date_edit()
        self.date_hint_label = hint_label()
        if self._paneled:
            return self._modern_time_page()
        body.addLayout(field_row(
            labelled("Start date", self.start_date_edit),
            labelled("End date", self.end_date_edit),
        ))
        body.addWidget(self._error_label("dates", self.start_date_edit, self.end_date_edit))
        body.addWidget(self.date_hint_label)
        body.addStretch(1)
        return card

    def _build_output_group(self) -> QFrame:
        card, body = section_card("Output", "Where the GeoTIFF is saved and in which projection.")

        self.crs_combo = QComboBox()
        for code, label in CRS_OPTIONS:
            self.crs_combo.addItem(label, code)
        self.crs_combo.setToolTip(
            "WGS 84 keeps longitude/latitude. A UTM zone uses metres, which suits area measurements."
        )

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setObjectName("PathField")
        self.output_dir_edit.setPlaceholderText(NO_PROJECT_FOLDER)
        self.output_dir_edit.setReadOnly(True)  # always the open project's downloads folder
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setObjectName("SecondaryButton")
        self.browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_button.hide()  # downloads cannot go elsewhere than the project
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self.output_dir_edit, 1)
        folder_row.addWidget(self.browse_button)

        # Register the output-folder error label in both layouts so _set_field_error("output_dir")
        # never misses, even though the modern layout hides the folder field itself.
        output_error = self._error_label("output_dir", self.output_dir_edit)

        if self._paneled:
            return self._modern_output_page(output_error)

        body.addWidget(labelled("Projection (CRS)", self.crs_combo, self._error_label("crs", self.crs_combo)))
        body.addWidget(labelled("Save to folder", folder_row, output_error))
        body.addWidget(self.estimate_label)
        body.addStretch(1)
        return card

    # ------------------------------------------------------------- behaviour
    def reset(self) -> None:
        today = QDate.currentDate()
        self.end_date_edit.setDate(today)
        self.start_date_edit.setDate(today.addMonths(-3))

        self.dataset_combo.setCurrentIndex(self.dataset_combo.findData("sentinel2_sr"))
        self._on_dataset_changed()

        self._imported_aoi = ""
        self._imported_name = ""
        self.aoi_file_label.setText(NO_FILE_TEXT)
        self.map_widget.show_geojson("")
        self._clear_drawn_shape()
        self.map_widget.clear_shape()
        self._clear_place_search()
        self.aoi_file_toggle.setChecked(True)
        self._on_aoi_mode_changed(AOI_FILE)

        self.crs_combo.setCurrentIndex(0)
        self.output_dir_edit.setText(self._project_downloads)
        self._analysis = ("", [])  # download only

        self._show_validation(ValidationDTO())
        self.status_banner.clear()

    def _current_dataset(self) -> DatasetInfo | None:
        return get_dataset(self.dataset_combo.currentData())

    def _on_dataset_changed(self) -> None:
        info = self._current_dataset()
        if info is None:
            return

        until = info.max_date.isoformat() if info.max_date else "present"
        self.dataset_info_label.setText(f"{info.collection_id}  ·  available {info.min_date.isoformat()} → {until}")
        self.date_hint_label.setText(f"{info.name} is available from {info.min_date.isoformat()} to {until}.")

        self.bands_combo.set_items([(band, band in info.default_bands) for band in info.bands])
        self.scale_spin.setValue(info.default_scale)
        self.composite_combo.setCurrentText(info.default_composite)

        self.cloud_spin.setEnabled(info.supports_cloud_filter)
        self.cloud_spin.setValue(20 if info.supports_cloud_filter else 0)
        self.cloud_spin.setToolTip(
            "Scenes with more cloud cover than this are excluded."
            if info.supports_cloud_filter else f"{info.name} has no cloud-cover filter."
        )

        self._apply_date_limits(info)
        if getattr(self, "modern_subtitle", None) is not None:
            self.modern_subtitle.setText(f"GEE-Assist · {info.name}")
        if self._analysis[0] and self._analysis[0] not in info.supported_analyses:
            self._analysis = ("", [])  # an analysis set from the terminal that this dataset cannot run

    def _apply_date_limits(self, info: DatasetInfo) -> None:
        lowest = _qdate(info.min_date)
        highest = _qdate(info.max_date) if info.max_date else QDate.currentDate()
        for edit in (self.start_date_edit, self.end_date_edit):
            edit.setDateRange(lowest, highest)  # out-of-range values are clamped
        if self.start_date_edit.date() >= self.end_date_edit.date():
            self.start_date_edit.setDate(self.end_date_edit.date().addMonths(-3))

    # ------------------------------------------------------------------- AOI
    def _on_aoi_mode_changed(self, mode: int) -> None:
        self.aoi_summary_stack.setCurrentIndex(mode)
        self.coords_box.setVisible(mode == AOI_DRAW)
        self.place_box.setVisible(mode == AOI_DRAW)
        self.map_widget.set_mode("draw" if mode == AOI_DRAW else "file")
        self._set_field_error("aoi", "")
        self._update_estimate()

    def _on_import_geojson(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import GeoJSON", "", "GeoJSON files (*.geojson *.json);;All files (*)"
        )
        if not path:  # 6c: user cancelled
            return
        try:
            self.import_geojson(path)
        except GeeAssistError:
            pass  # shown under the area

    def import_geojson(self, path: str) -> None:
        """UC-04: read a GeoJSON file into the form. Raises the import error after showing it."""
        try:
            aoi = self._facade.import_aoi(path)
        except GeeAssistError as exc:  # 6a / 6b
            self._imported_aoi = ""
            self.aoi_file_label.setText(NO_FILE_TEXT)
            self.map_widget.show_geojson("")
            self._set_field_error("aoi", str(exc))
            self._update_estimate()
            raise
        self.set_imported_area(aoi, Path(path).name)

    def set_imported_area(self, aoi: str, name: str) -> None:
        """Show ``aoi`` (GeoJSON) as the imported file's area and switch to "GeoJSON file"."""
        self._imported_aoi = aoi
        self._imported_name = name
        geometry = json.loads(aoi)
        min_lon, min_lat, max_lon, max_lat = bbox_of(geometry)
        self.aoi_file_label.setText(
            f"<b>{self._imported_name}</b> · {geometry['type']}<br>"
            f"Extent: lon {min_lon:.4f} → {max_lon:.4f}, lat {min_lat:.4f} → {max_lat:.4f}"
        )
        self.aoi_file_toggle.setChecked(True)
        self._on_aoi_mode_changed(AOI_FILE)
        self.map_widget.show_geojson(aoi)
        self._set_field_error("aoi", "")
        self._update_estimate()

    def _set_bbox_spins(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> None:
        for spin, value in zip(self._bbox_spins, (min_lon, min_lat, max_lon, max_lat)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        # Remember what the spins now hold, so a later editingFinished (which also fires just on
        # focus-out) does not mistake an unchanged box for a typed one and overwrite the AOI.
        self._bbox_snapshot = self._bbox_values()

    def _bbox_values(self) -> tuple[float, float, float, float]:
        lon_a, lat_a, lon_b, lat_b = (s.value() for s in self._bbox_spins)
        return min(lon_a, lon_b), min(lat_a, lat_b), max(lon_a, lon_b), max(lat_a, lat_b)

    def _set_drawn_shape(self, geometry: dict, name: str, summary: str, sync_spins: bool = True) -> None:
        self._drawn_aoi = json.dumps(geometry)
        self._drawn_name = name
        self.shape_label.setText(summary)
        if sync_spins:
            min_lon, min_lat, max_lon, max_lat = bbox_of(geometry)
            self._set_bbox_spins(max(min_lon, -180), max(min_lat, -90), min(max_lon, 180), min(max_lat, 90))
        self._set_field_error("aoi", "")
        self._update_estimate()

    def _clear_drawn_shape(self) -> None:
        self._drawn_aoi = ""
        self._drawn_name = ""
        self.shape_label.setText(NO_SHAPE_TEXT)
        self._set_bbox_spins(0.0, 0.0, 0.0, 0.0)
        self._update_estimate()

    def _on_map_bbox_drawn(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> None:
        min_lon, min_lat = max(min_lon, -180), max(min_lat, -90)
        max_lon, max_lat = min(max_lon, 180), min(max_lat, 90)
        self._set_drawn_shape(
            bbox_polygon(min_lon, min_lat, max_lon, max_lat), "Rectangle", "<b>Rectangle</b> drawn on the map."
        )

    def _on_map_circle_drawn(self, lon: float, lat: float, radius_m: float) -> None:
        radius = format_distance(radius_m)
        self._set_drawn_shape(
            circle_polygon(lon, lat, radius_m),
            f"Circle (r = {radius})",
            f"<b>Circle</b> · centre {lon:.4f}, {lat:.4f} · radius {radius}",
        )

    def _on_map_polygon_drawn(self, geometry_text: str) -> None:
        try:
            geometry = polygon_from_geojson(geometry_text)
            vertices = vertex_count(geometry)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            self._clear_drawn_shape()
            self._set_field_error("aoi", "Could not read the polygon drawn on the map. Please draw it again.")
            return
        self._set_drawn_shape(geometry, f"Polygon ({vertices} vertices)", f"<b>Polygon</b> · {vertices} vertices")

    def _on_map_shape_cleared(self) -> None:
        self._clear_drawn_shape()

    def _on_bbox_typed(self) -> None:
        bbox = self._bbox_values()
        # editingFinished also fires when the spins merely lose focus (a click elsewhere on the
        # page). If the coordinates are unchanged, keep the current AOI — do not replace a searched
        # or imported boundary (e.g. Lahore's 463-vertex outline) with its 4-corner bounding box.
        if self._bbox_snapshot is not None and all(abs(a - b) < 1e-9 for a, b in zip(bbox, self._bbox_snapshot)):
            return
        self._bbox_snapshot = bbox
        min_lon, min_lat, max_lon, max_lat = bbox
        if min_lon < max_lon and min_lat < max_lat:
            self._set_drawn_shape(
                bbox_polygon(min_lon, min_lat, max_lon, max_lat),
                "Rectangle",
                "<b>Rectangle</b> from the typed coordinates.",
                sync_spins=False,
            )
            self.map_widget.set_bbox(min_lon, min_lat, max_lon, max_lat, fit=True)

    # ------------------------------------------------------- place search
    def _on_place_search(self) -> None:
        name = self.place_edit.text().strip()
        if not name:
            self._set_field_error("aoi", "Type the name of a city, region or country to search for.")
            return
        self._place_search_id += 1
        search_id = self._place_search_id
        self._set_place_busy(True)
        self._set_field_error("aoi", "")
        run_task(
            self, self._facade.search_place, name,
            on_success=lambda places: self._on_places_found(search_id, places),
            on_error=lambda exc: self._on_place_search_failed(search_id, exc),
        )

    def _on_places_found(self, search_id: int, places: list[PlaceDTO]) -> None:
        if search_id != self._place_search_id:
            return  # a newer search (or a reset) replaced this one
        self._set_place_busy(False)
        self.show_places(places)

    def _on_place_search_failed(self, search_id: int, exc: Exception) -> None:
        if search_id != self._place_search_id:
            return
        self._set_place_busy(False)
        self._set_field_error(
            "aoi", str(exc) if isinstance(exc, GeeAssistError) else "Place search failed. Please try again."
        )

    def show_places(self, places: list[PlaceDTO]) -> None:
        """Use the first place's boundary as the AOI and list the other matches to choose from."""
        self._places = list(places)
        self.place_results_combo.clear()
        for place in self._places:
            self.place_results_combo.addItem(f"{place.display_name} ({place.kind})")
            self.place_results_combo.setItemData(
                self.place_results_combo.count() - 1, place.display_name, Qt.ItemDataRole.ToolTipRole
            )
        self.place_results_combo.setVisible(len(self._places) > 1)
        if self._places:
            self.place_results_combo.setCurrentIndex(0)
            self.set_place_area(self._places[0])

    def _on_place_chosen(self, index: int) -> None:
        if 0 <= index < len(self._places):
            self.set_place_area(self._places[index])

    def set_place_area(self, place: PlaceDTO) -> None:
        """Make ``place``'s exact boundary the AOI, shown on the map in "Draw on map" mode."""
        geometry = json.loads(place.aoi)
        self.aoi_draw_toggle.setChecked(True)
        self._on_aoi_mode_changed(AOI_DRAW)
        self._set_drawn_shape(
            geometry, place.name,
            f"<b>{place.name}</b> · {place.kind} boundary · {vertex_count(geometry):,} vertices",
        )
        self.map_widget.set_shape(place.aoi, fit=True)

    def _set_place_busy(self, busy: bool) -> None:
        self.place_search_button.setEnabled(not busy)
        self.place_edit.setEnabled(not busy)
        self.place_search_button.setText("Searching…" if busy else "Find place")

    def _clear_place_search(self) -> None:
        self._place_search_id += 1  # drop any answer still on its way
        self._places = []
        self.place_results_combo.clear()
        self.place_results_combo.hide()
        self.place_edit.clear()
        self._set_place_busy(False)

    # ------------------------------------------------------- natural language
    def _on_query_submitted(self, text: str) -> None:
        self.assistant.set_busy(True)
        run_task(
            self, self._facade.submit_query, text,
            on_success=self._on_query_interpreted, on_error=self._on_query_failed,
        )

    def _on_query_interpreted(self, form: FormDTO) -> None:
        self.assistant.set_busy(False)
        filled = self.apply_form(form)
        notes = " ".join(form.notes)

        if not filled:
            self.assistant.show_info(
                form.clarification
                or "No form values could be taken from that request. Try naming a place, dates or a dataset."
            )
            return

        recognised = list(dict.fromkeys(e.text for e in form.entities))
        summary = " ".join(filter(None, (
            f"Recognised: {' · '.join(recognised)}." if recognised else "",
            f"Filled: {', '.join(filled)}.",
        )))
        if form.clarification:  # partly understood: keep the card open with Gemini's question
            self.assistant.show_info(f"{summary} {form.clarification}")
        else:
            self.assistant.collapse()
        self.status_banner.show_info(" ".join(filter(None, (summary, notes, "Check the values, then press Submit Parameters."))))

    def _on_query_failed(self, exc: Exception) -> None:
        self.assistant.set_busy(False)
        self.assistant.show_error(str(exc) if isinstance(exc, GeeAssistError) else "Something went wrong. Please try again.")

    def apply_form(self, form: FormDTO) -> list[str]:
        """Put the values of ``form`` into the widgets. Returns the names of the parts filled.

        Empty values leave the current field untouched; the output settings
        (projection, folder) are never changed by a query.
        """
        filled: list[str] = []
        self._show_validation(ValidationDTO())  # clear old errors

        index = self.dataset_combo.findData(form.dataset) if form.dataset else -1
        if index >= 0:
            self.dataset_combo.setCurrentIndex(index)
            self._on_dataset_changed()  # also when it was already selected: resets dependent fields
            filled.append("dataset")
            if form.bands:
                self.bands_combo.set_checked(form.bands)
                filled.append("bands")
            if form.scale:
                self.scale_spin.setValue(form.scale)
            if form.max_cloud_cover is not None and self.cloud_spin.isEnabled():
                self.cloud_spin.setValue(form.max_cloud_cover)
                filled.append("cloud cover")
            if form.composite:
                self.composite_combo.setCurrentText(form.composite)

        if form.start_date or form.end_date:
            if form.end_date:
                self.end_date_edit.setDate(_qdate(form.end_date))
            if form.start_date:
                self.start_date_edit.setDate(_qdate(form.start_date))
            filled.append("dates")

        if form.aoi:
            geometry = json.loads(form.aoi)
            name = form.aoi_name or "Area from your request"
            self.aoi_draw_toggle.setChecked(True)
            self._on_aoi_mode_changed(AOI_DRAW)
            self._set_drawn_shape(
                geometry, name,
                f"<b>{name}</b> · area from your request ({vertex_count(geometry):,} vertices). "
                "Adjust it on the map if needed.",
            )
            self.map_widget.set_shape(form.aoi, fit=True)  # the place's outline, not its bounding box
            filled.append(f"area ({name})")

        return filled

    # --------------------------------------------- setting fields (gkonsol's "form set")
    # The values are checked by the caller; these put them in the fields as the user would.
    def set_dataset(self, key: str) -> None:
        index = self.dataset_combo.findData(key)
        if index < 0:
            raise ValueError(f"Unknown dataset {key!r}")
        self.dataset_combo.setCurrentIndex(index)
        self._on_dataset_changed()  # also when it was already chosen: its defaults come back

    def set_bands(self, bands: list[str]) -> None:
        self.bands_combo.set_checked(bands)  # the size estimate follows

    def set_scale(self, metres: int) -> None:
        self.scale_spin.setValue(metres)

    def set_cloud_cover(self, percent: int) -> None:
        self.cloud_spin.setValue(percent)

    def set_composite(self, method: str) -> None:
        self.composite_combo.setCurrentText(method)

    def set_dates(self, start, end) -> None:
        self.end_date_edit.setDate(_qdate(end))
        self.start_date_edit.setDate(_qdate(start))
        self._set_field_error("dates", "")

    def set_drawn_area(self, aoi: str, name: str) -> None:
        """Show ``aoi`` (GeoJSON) as the area drawn on the map, and switch to "Draw on map"."""
        geometry = json.loads(aoi)
        self.aoi_draw_toggle.setChecked(True)
        self._on_aoi_mode_changed(AOI_DRAW)
        self._set_drawn_shape(geometry, name, f"<b>{name}</b> · set in gkonsol.")
        min_lon, min_lat, max_lon, max_lat = bbox_of(geometry)
        self.map_widget.set_bbox(min_lon, min_lat, max_lon, max_lat, fit=True)

    def clear_area(self) -> None:
        self._imported_aoi = ""
        self._imported_name = ""
        self.aoi_file_label.setText(NO_FILE_TEXT)
        self.map_widget.show_geojson("")
        self._clear_drawn_shape()
        self.map_widget.clear_shape()
        self._clear_place_search()

    def set_crs(self, code: str) -> None:
        index = self.crs_combo.findData(code)
        if index < 0:
            raise ValueError(f"Unknown projection {code!r}")
        self.crs_combo.setCurrentIndex(index)

    def set_project(self, project) -> None:
        """Downloads go into ``project``'s downloads folder (a ProjectDTO, or None when no project is open)."""
        self._project_downloads = project.downloads_dir if project is not None else ""
        self.output_dir_edit.setText(self._project_downloads)
        self.output_dir_edit.setToolTip(
            "Downloads are saved in the open project's downloads folder." if project is not None
            else NO_PROJECT_FOLDER
        )
        self._set_field_error("output_dir", "")

    def set_output_dir(self, folder: str) -> None:
        self.output_dir_edit.setText(folder)
        self._set_field_error("output_dir", "")

    def set_analysis(self, analysis_type: str, processes: list[str]) -> None:
        """Only for gkonsol's ``form set analysis``: the form on screen no longer has an analysis section
        (analyses are run on the Analysis page). "" means download only."""
        if analysis_type and analysis_type not in ANALYSIS_CATEGORIES:
            raise ValueError(f"Unknown analysis {analysis_type!r}")
        self._analysis = (analysis_type, list(processes) if analysis_type else [])

    # ---------------------------------------------------------------- output
    def _on_browse_output(self) -> None:
        start = self.output_dir_edit.text().strip() or str(DEFAULT_DOWNLOAD_DIR)
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", start)
        if folder:  # empty when the user cancels
            self.output_dir_edit.setText(str(Path(folder)))
            self._set_field_error("output_dir", "")

    def _update_estimate(self, *_args) -> None:
        """Rough GeoTIFF size and how many GEE requests (tiles) the download needs."""
        self._refresh_vertices()  # modern layout only; no-op otherwise
        self._update_required()
        if not hasattr(self, "estimate_label"):
            return  # still building the form
        aoi, _name = self._current_aoi()
        bands = self.bands_combo.checked()
        if not aoi or not bands:
            self.estimate_label.setText("Size estimate appears once an area and at least one band are chosen.")
            return
        # Sizes are float32 (file size); GEE counts 5 bytes per pixel and band against its
        # request limit, so the limit is scaled to count requests the way GEE does.
        estimate = estimate_download(
            json.loads(aoi), self.scale_spin.value(), len(bands),
            BYTES_PER_PIXEL, GEE_MAX_REQUEST_BYTES * BYTES_PER_PIXEL // GEE_REQUEST_BYTES_PER_PIXEL,
            GEE_MAX_GRID_DIMENSION,
        )
        tiles = "1 request" if estimate.requests == 1 else f"{estimate.requests:,} tiles"
        self.estimate_label.setText(
            f"Estimated download: {estimate.width_px:,} × {estimate.height_px:,} px · "
            f"{len(bands)} band{'s' if len(bands) != 1 else ''} · ~{format_bytes(estimate.total_bytes)} "
            f"→ {tiles} (GEE allows {format_bytes(GEE_MAX_REQUEST_BYTES)} per request)."
        )

    # ---------------------------------------------------------------- submit
    def _current_aoi(self) -> tuple[str, str]:
        if self.aoi_file_toggle.isChecked():
            return self._imported_aoi, self._imported_name
        return self._drawn_aoi, self._drawn_name

    def collect_form(self) -> FormDTO:
        """Build a FormDTO from the current widget values."""
        aoi, aoi_name = self._current_aoi()

        return FormDTO(
            dataset=self.dataset_combo.currentData() or "",
            bands=self.bands_combo.checked(),
            scale=self.scale_spin.value(),
            max_cloud_cover=self.cloud_spin.value() if self.cloud_spin.isEnabled() else None,
            composite=self.composite_combo.currentText(),
            aoi=aoi,
            aoi_name=aoi_name,
            start_date=self.start_date_edit.date().toPyDate(),
            end_date=self.end_date_edit.date().toPyDate(),
            crs=self.crs_combo.currentData(),
            output_dir=self.output_dir_edit.text().strip(),
            analysis_type=self._analysis[0],
            processes=list(self._analysis[1]),
            source="form",
        )

    def _on_submit(self) -> None:
        try:
            self.submit()
        except GeeAssistError:
            pass  # shown in the status banner

    def submit(self) -> ValidationDTO:
        """Validate the form and keep it when valid (Submit Parameters). Errors show in the form too."""
        form = self.collect_form()
        try:
            result = self._facade.submit_form(form)
        except GeeAssistError as exc:
            self.status_banner.show_error(str(exc))
            raise

        self._show_validation(result)
        if result.is_valid:
            self.request_kept.emit(form)
        else:
            first = next((key for key in FIELD_ORDER if key in result.errors), None)
            if first:
                self.go_to_field(first)  # take the user straight to the first field to fix
        return result

    def _show_validation(self, result: ValidationDTO) -> None:
        self._field_errors = {key for key, message in result.errors.items() if message}
        for key in self._error_labels:
            self._set_field_error(key, result.errors.get(key, ""))
        if result.is_valid:
            self.status_banner.show_success(result.message)
        else:
            # Each field's error already shows under the field (and in the "Still needed" links),
            # so the banner would only repeat it. Keep the banner for errors that have no field on
            # the page (e.g. an analysis set from the terminal); otherwise leave it empty.
            elsewhere = [message for key, message in result.errors.items()
                         if message and key not in self._error_labels]
            if elsewhere:
                self.status_banner.show_error(" ".join(elsewhere).strip())
            else:
                self.status_banner.clear()

    def _set_field_error(self, key: str, message: str) -> None:
        label = self._error_labels[key]
        label.setText(message)
        label.setVisible(bool(message))
        for target in self._error_targets.get(key, ()):
            set_invalid(target, bool(message))
        if not message:
            self._field_errors.discard(key)
        self._update_required()

    # ------------------------------------------------------------- required fields
    def missing_fields(self) -> list[str]:
        """Keys of the required fields that are still empty, in REQUIRED_FIELDS order."""
        if not hasattr(self, "output_dir_edit") or not hasattr(self, "bands_combo"):
            return []  # still building the form
        aoi, _name = self._current_aoi()
        empty = {
            "aoi": not aoi,
            "dataset": not self.dataset_combo.currentData(),
            "bands": not self.bands_combo.checked(),
            "output_dir": not self.output_dir_edit.text().strip(),
        }
        return [key for key, _label in REQUIRED_FIELDS if empty[key]]

    def _update_required(self, *_args) -> None:
        """Refresh the "Still needed" links and mark the tabs that need attention."""
        if not hasattr(self, "required_label"):
            return
        missing = self.missing_fields()
        labels = dict(REQUIRED_FIELDS)
        # The folder is always the open project's: an empty one means no project is open,
        # so name the actual fix rather than a "Project folder" field the user cannot type in.
        labels["output_dir"] = "Create or open a project"
        if missing:
            links = "  ·  ".join(
                f'<a href="{key}" style="color:{_needed()}; text-decoration:underline;">{labels[key]}</a>'
                for key in missing
            )
            self.required_label.setText(f'<span style="color:{_needed()};">● Still needed:</span>&nbsp; {links}')
            self.required_label.setToolTip("Click a field to go to it.")
        else:
            self.required_label.setText(f'<span style="color:{_done()};">✓ All required fields are filled.</span>')
            self.required_label.setToolTip("")

        for index, button in enumerate(self._modern_tab_buttons):
            keys = [key for key, tab in FIELD_TABS.items() if tab == index]
            if any(key in self._field_errors for key in keys):
                state = "error"
            elif any(key in missing for key in keys):
                state = "missing"
            else:
                state = ""
            if button.property("state") != state:
                button.setProperty("state", state)
                button.setText(f"{TAB_NAMES[index]}  ●" if state else TAB_NAMES[index])
                button.setToolTip({"error": "Some fields here need fixing",
                                   "missing": "Required fields here are still empty"}.get(state, ""))
                button.style().unpolish(button)
                button.style().polish(button)

    def _field_widget(self, key: str) -> QWidget | None:
        """The widget to focus for ``key``."""
        if key == "aoi":
            return self.import_button if self.aoi_file_toggle.isChecked() else self.place_edit
        if key == "output_dir":
            return self.output_dir_edit if not self._paneled else self._error_labels.get("output_dir")
        targets = self._error_targets.get(key, ())
        return targets[0] if targets else self._error_labels.get(key)

    def go_to_field(self, key: str) -> None:
        """Show the field ``key`` (switching tab in the modern layout), scroll to it and focus it."""
        if self._paneled and key in FIELD_TABS:
            index = FIELD_TABS[key]
            self._modern_tabs.button(index).setChecked(True)
            self._modern_stack.setCurrentIndex(index)
            if self._studio:
                self._set_studio_step_text(index)
        if key == "output_dir" and not self.output_dir_edit.text().strip():
            self.status_banner.show_error(NO_PROJECT_FOLDER + ".")
        widget = self._field_widget(key)
        if widget is None:
            return

        def reveal() -> None:
            parent = widget.parentWidget()
            while parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parentWidget()
            if parent is not None and widget.isVisible():
                parent.ensureWidgetVisible(widget, 40, 60)
            if widget.focusPolicy() != Qt.FocusPolicy.NoFocus and widget.isEnabled():
                widget.setFocus(Qt.FocusReason.OtherFocusReason)

        QTimer.singleShot(0, reveal)  # after the tab switch is laid out

    # ------------------------------------------------------------- responsive layout
    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self._modern:
            width = max(MODERN_PANEL_MIN_WIDTH, min(MODERN_PANEL_WIDTH, int(self.width() * 0.42)))
            self._modern_panel.setFixedWidth(width)
            self.modern_subtitle.setVisible(self.height() >= SHORT_PAGE)
        elif self._studio:
            # Drop the map caption and header subtitle on short screens to buy vertical room.
            self.modern_subtitle.setVisible(self.height() >= SHORT_PAGE)
            self._studio_map_caption.setVisible(self.height() >= SHORT_PAGE)
        else:
            narrow = self.width() < NARROW_PAGE
            self._time_output_row.setDirection(
                QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
            )
