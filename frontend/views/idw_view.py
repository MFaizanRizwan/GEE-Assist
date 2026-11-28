"""IDW Interpolation page: turn point measurements into a continuous surface.

IDW serves any measured quantity: soil pH, rainfall, temperature, groundwater depth,
pollution… Open a point shapefile or a CSV of points (longitude and latitude columns in
degrees), pick the numeric field to interpolate, set the IDW parameters (power, number of
neighbours, search radius, output resolution) and run.

The result is shown on a world map whose layers stack, bottom to top: the basemap, the
surface, the boundaries (a polygon shapefile: cities, districts, fields…) and the sample
points; each can be shown or hidden. Ctrl+click an area on the map (or tick it in the
list) to select it: the next run covers it, and with "Clip to the selected area" the
surface stops sharply at its edge. The surface is coloured continuously or in value
classes (equal interval, quantile, natural breaks), in the classic IDW colours (yellow,
orange, red) or Viridis, with a legend of the ranges. "Picture" shows the surface alone
(also without an internet connection). "Save surface…" writes a GeoTIFF; "Export PDF…"
lays out a printable map with a north arrow, a scale bar and the legend.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QBuffer, QIODevice, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.interpolation_dto import IDWParamsDTO, IDWResultDTO, SamplePointDTO
from backend.dto.map_dto import LegendDTO
from backend.dto.vector_dto import MULTIPOINT, POINT, POLYGON, VectorLayerDTO
from backend.exceptions import GeeAssistError
from frontend import theme, theming
from frontend.widgets import idw_colours
from frontend.widgets.flow_layout import FlowLayout
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.layer_map_widget import (
    LayerMapWidget,
    area_label,
    boundaries_geojson,
    label_field_of,
    polygons_of,
)
from frontend.widgets.map_area import MapArea
from frontend.widgets.map_overlays import LegendOverlay, ValueReadout
from frontend.widgets.raster_canvas import rgba_to_image
from frontend.widgets.raster_legend import RasterLegend, format_value
from frontend.widgets.toggle_switch import ToggleSwitch
from frontend.workers.task_worker import run_task

PANEL_WIDTH = 340
HOVER_DELAY_MS = 40
WORLD, PICTURE = 0, 1


def _stylesheet():
    return f"""
#IdwPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20.6pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#IdwCanvasCard, QFrame#IdwPanel {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px;
}}
QFrame#IdwPanel QLabel {{ background: transparent; }}
QLabel#SectionTitle {{ color: {theme.MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#Value {{ color: {theme.INK}; }}
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px;
    padding: 5px 8px; color: {theme.INK};
}}
QListWidget {{ background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; color: {theme.TEXT}; }}
QPushButton#ViewTab {{
    padding: 5px 12px; border-radius: 8px; border: 1px solid {theme.BORDER_STRONG}; background: {theme.FIELD_BG};
    color: {theme.TEXT}; font-weight: 600;
}}
QPushButton#ViewTab:checked {{ border-color: {theme.LEAF}; color: {theme.INK}; background: {theme.ACCENT_SOFT or theme.MINT}; }}
"""


def _section(title: str) -> QLabel:
    return QLabel(title.upper(), objectName="SectionTitle")


def _muted(text: str) -> QLabel:
    label = QLabel(text, objectName="Muted")
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class IdwView(QWidget):
    surface_ready = pyqtSignal(object)  # the IDWResultDTO, after a run (for tests/hooks)

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("IdwPage")
        theming.styled(self, _stylesheet)
        self._facade = facade
        self._layer: VectorLayerDTO | None = None
        self._csv_path = ""   # the CSV the points came from ("" for a shapefile)
        self.result: IDWResultDTO | None = None
        self._pointer: tuple[float, float] | None = None
        self._boundary: VectorLayerDTO | None = None
        self.selected: set[int] = set()       # boundary features chosen (Ctrl+click or the list)
        self._rgba: np.ndarray | None = None  # the surface as coloured now
        self._legend: tuple = ()              # ("scale", colours, low, high) or ("classes", rows)

        self.title = QLabel("IDW Interpolation", objectName="PageTitle")
        self.subtitle = QLabel("Interpolate measured points into a surface — soil pH, rainfall, temperature, "
                               "groundwater, pollution… From a point shapefile or a CSV.", objectName="PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.banner = StatusBanner()

        self.open_button = QPushButton("Open points…", objectName="PrimaryButton")
        self.boundary_button = QPushButton("Open boundaries…", objectName="SecondaryButton")
        self.boundary_button.setToolTip("A polygon shapefile (cities, districts, fields…) shown over the map; "
                                        "Ctrl+click an area to interpolate within it")
        self.run_button = QPushButton("Run IDW", objectName="PrimaryButton")
        self.save_button = QPushButton("Save surface…", objectName="SecondaryButton")
        self.pdf_button = QPushButton("Export PDF…", objectName="SecondaryButton")
        self.pdf_button.setToolTip("Lay out a printable map: title, north arrow, scale bar, legend, boundaries")
        self.fit_button = QPushButton("Fit to window", objectName="SecondaryButton")
        self.folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        toolbar = FlowLayout(spacing=8)
        for button in (self.open_button, self.boundary_button, self.run_button, self.save_button, self.pdf_button,
                       self.fit_button, self.folder_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            toolbar.addWidget(button)

        # ---- the map: the world map with its layers, or the surface alone (a picture)
        self.world = LayerMapWidget()
        self.map_legend = LegendOverlay(False, self.world)
        self.map_readout = ValueReadout(False, self.world)
        self.picture = MapArea(dark=False)
        self.canvas = self.picture.canvas          # kept name: the plain surface
        self.picture.set_value_probe(self._value_at_pixel)
        self.views = QStackedWidget()
        self.views.addWidget(self.world)
        self.views.addWidget(self.picture)
        self.view_group = QButtonGroup(self)
        self.world_tab = QPushButton("World map", objectName="ViewTab")
        self.picture_tab = QPushButton("Picture", objectName="ViewTab")
        view_row = QHBoxLayout()
        view_row.setSpacing(6)
        for index, tab in enumerate((self.world_tab, self.picture_tab)):
            tab.setCheckable(True)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            self.view_group.addButton(tab, index)
            view_row.addWidget(tab)
        view_row.addStretch(1)
        self.map_hint = QLabel("Ctrl+click an area to select it", objectName="Muted")
        view_row.addWidget(self.map_hint)
        self.view_group.idClicked.connect(self.show_view)
        canvas_card = QFrame(objectName="IdwCanvasCard")
        canvas_layout = QVBoxLayout(canvas_card)
        canvas_layout.setContentsMargins(8, 8, 8, 8)
        canvas_layout.setSpacing(6)
        canvas_layout.addLayout(view_row)
        canvas_layout.addWidget(self.views, 1)

        self._build_panel()

        # ---- the sample points, row by row (a CSV's own columns, else coordinates + attributes)
        self.points_title = QLabel("SAMPLE POINTS", objectName="SectionTitle")
        self.points_note = QLabel("Open points to see them here; click a row to find it on the map.",
                                  objectName="Muted")
        self.points_table = QTableWidget(0, 0)
        self.points_table.verticalHeader().hide()
        self.points_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.points_table.setAlternatingRowColors(True)
        self.points_table.itemSelectionChanged.connect(self._on_point_row)
        points_card = QFrame(objectName="IdwCanvasCard")
        points_layout = QVBoxLayout(points_card)
        points_layout.setContentsMargins(12, 10, 12, 10)
        points_layout.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(self.points_title)
        head.addStretch(1)
        head.addWidget(self.points_note)
        points_layout.addLayout(head)
        points_layout.addWidget(self.points_table, 1)
        self.map_split = QSplitter(Qt.Orientation.Vertical)
        self.map_split.addWidget(canvas_card)
        self.map_split.addWidget(points_card)
        self.map_split.setStretchFactor(0, 3)
        self.map_split.setStretchFactor(1, 1)
        self.map_split.setChildrenCollapsible(False)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.map_split, 1)
        body.addWidget(self._panel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addLayout(toolbar)
        layout.addWidget(self.banner)
        layout.addLayout(body, 1)

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._read_value)

        self.open_button.clicked.connect(self.open_points)
        self.boundary_button.clicked.connect(self.open_boundaries)
        self.run_button.clicked.connect(self.run)
        self.save_button.clicked.connect(self.save_surface)
        self.pdf_button.clicked.connect(self.export_pdf)
        self.fit_button.clicked.connect(self.fit)
        self.folder_button.clicked.connect(self._open_folder)
        self.world.feature_toggled.connect(self.toggle_area)
        self.world.pointer_moved.connect(self._on_world_pointer)
        self.world.pointer_left.connect(self._on_left)
        self.show_view(WORLD if self.world.available else PICTURE)
        self.world_tab.setEnabled(self.world.available)
        self._set_ready(False)

    # ================================================================ panel
    def _build_panel(self) -> None:
        self.field_box = QComboBox()
        self.field_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.field_box.currentIndexChanged.connect(lambda *_: self._send_points())   # the points' labels
        # A CSV's coordinate columns (guessed from their names; the user can correct them).
        self.lon_box = QComboBox()
        self.lat_box = QComboBox()
        for box in (self.lon_box, self.lat_box):
            box.setCursor(Qt.CursorShape.PointingHandCursor)
            box.currentIndexChanged.connect(self._on_coordinate_column)
        self.power = self._dspin(0.1, 10.0, 2.0, 0.5, "")
        self.neighbours = QSpinBox()
        self.neighbours.setRange(0, 1000)
        self.neighbours.setValue(12)
        self.neighbours.setSpecialValueText("all")
        self.radius = self._dspin(0.0, 180.0, 0.0, 0.1, "°")
        self.radius.setDecimals(3)
        self.radius.setSpecialValueText("none")
        self.resolution = QSpinBox()
        self.resolution.setRange(16, 1200)
        self.resolution.setSingleStep(50)
        self.resolution.setValue(400)
        self.resolution.setSuffix(" px")

        params = QGridLayout()
        params.setHorizontalSpacing(12)
        params.setVerticalSpacing(6)
        self._coordinate_rows = []
        for row, (name, widget) in enumerate((("Longitude", self.lon_box), ("Latitude", self.lat_box),
                                              ("Value field", self.field_box), ("Power", self.power),
                                              ("Neighbours", self.neighbours), ("Search radius", self.radius),
                                              ("Resolution", self.resolution))):
            label = QLabel(name, objectName="Muted")
            params.addWidget(label, row, 0)
            params.addWidget(widget, row, 1)
            if widget in (self.lon_box, self.lat_box):
                self._coordinate_rows += [label, widget]
        params.setColumnStretch(1, 1)
        self._show_coordinate_columns(False)

        # ---- the area: boundaries, the selection and clipping
        self.name_box = QComboBox()
        self.name_box.setToolTip("The attribute that names each area")
        self.name_box.currentIndexChanged.connect(self._on_name_field)
        self.area_filter = QLineEdit()
        self.area_filter.setPlaceholderText("Find an area…")
        self.area_filter.textChanged.connect(self._filter_areas)
        self.area_list = QListWidget()
        self.area_list.setMinimumHeight(120)
        self.area_list.setMaximumHeight(170)
        self.area_list.itemChanged.connect(self._on_area_ticked)
        self.area_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area_list.setTextElideMode(Qt.TextElideMode.ElideRight)   # long names end in "…"
        self.selection_label = _muted("Open a boundary shapefile, then Ctrl+click areas on the map (or tick them "
                                      "here) to interpolate within them.")
        self.clear_selection_button = QPushButton("Clear selection", objectName="SecondaryButton")
        self.clear_selection_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_selection_button.clicked.connect(lambda: self.set_selection(set()))
        self.clip_toggle = ToggleSwitch("Clip to the selected area (sharp edge)")
        self.clip_toggle.setChecked(True)
        self.clip_toggle.setToolTip("On: the surface stops exactly at the selected boundary.\n"
                                    "Off: the surface covers the area but also spreads beyond it.")

        # ---- colours and classes
        self.classic_toggle = ToggleSwitch("Classic IDW colours (yellow – orange – red)")
        self.classic_toggle.setChecked(True)
        self.method_box = QComboBox()
        for key, label in idw_colours.METHODS:
            self.method_box.addItem(label, key)
        self.method_box.setCurrentIndex(self.method_box.findData(idw_colours.NATURAL))
        self.classes = QSpinBox()
        self.classes.setRange(2, 12)
        self.classes.setValue(5)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(85)
        for widget in (self.classic_toggle, self.classes, self.method_box):
            signal = widget.toggled if isinstance(widget, ToggleSwitch) else (
                widget.valueChanged if isinstance(widget, QSpinBox) else widget.currentIndexChanged)
            signal.connect(lambda *_: self.recolour())
        self.opacity.valueChanged.connect(lambda v: self.world.set_surface_opacity(v / 100))
        symbology = QGridLayout()
        symbology.setHorizontalSpacing(12)
        symbology.setVerticalSpacing(6)
        for row, (name, widget) in enumerate((("Classes", self.method_box), ("Number", self.classes),
                                              ("Opacity", self.opacity))):
            symbology.addWidget(QLabel(name, objectName="Muted"), row, 0)
            symbology.addWidget(widget, row, 1)
        symbology.setColumnStretch(1, 1)

        # ---- layers
        self.layer_toggles: dict[str, ToggleSwitch] = {}
        layers = QVBoxLayout()
        layers.setSpacing(4)
        for key, label in (("basemap", "Basemap"), ("surface", "Surface"), ("boundaries", "Boundaries"),
                           ("points", "Sample points")):
            toggle = ToggleSwitch(label)
            toggle.setChecked(True)
            toggle.toggled.connect(lambda on, k=key: self.world.set_layer_visible(k, on))
            self.layer_toggles[key] = toggle
            layers.addWidget(toggle)
        # Keep only the selected area: hide the other areas' outlines and the points outside it
        # (shown only; IDW still uses every point, so values near the edge stay right).
        self.focus_toggles: dict[str, ToggleSwitch] = {}
        for key, label, tip in (
                ("other_areas", "Other areas' boundaries", "Off: only the selected area's outline is drawn"),
                ("outside_points", "Points outside the selected area",
                 "Off: only the sample points inside the selected area are shown (IDW still uses all of them)")):
            toggle = ToggleSwitch(label)
            toggle.setChecked(True)
            toggle.setToolTip(tip)
            self.focus_toggles[key] = toggle
            layers.addWidget(toggle)
        self.focus_toggles["other_areas"].toggled.connect(self._on_other_areas)
        self.focus_toggles["outside_points"].toggled.connect(lambda *_: self._points_changed())
        self.basemap_box = QComboBox()
        self.basemap_box.addItem("Streets", "streets")
        self.basemap_box.addItem("Satellite", "satellite")
        self.basemap_box.currentIndexChanged.connect(lambda *_: self.world.set_basemap(self.basemap_box.currentData()))
        layers.addWidget(self.basemap_box)

        self.legend = RasterLegend()
        self.pointer_label = QLabel("Run IDW, then point at the surface to read a value.", objectName="Muted")
        self.pointer_label.setWordWrap(True)

        self.detail_labels: dict[str, QLabel] = {}
        details = QGridLayout()
        details.setHorizontalSpacing(12)
        details.setVerticalSpacing(4)
        for row, (key, name) in enumerate((("points", "Sample points"), ("field", "Field"), ("range", "Value range"),
                                           ("cell", "Cell size"), ("extent", "Extent"))):
            value = QLabel("–", objectName="Value")
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.addWidget(QLabel(name, objectName="Muted"), row, 0, Qt.AlignmentFlag.AlignTop)
            details.addWidget(value, row, 1)
            self.detail_labels[key] = value
        details.setColumnStretch(1, 1)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(8)
        column.addWidget(_section("Interpolation"))
        column.addLayout(params)
        column.addSpacing(6)
        column.addWidget(_section("Area"))
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Names from", objectName="Muted"))
        name_row.addWidget(self.name_box, 1)
        column.addLayout(name_row)
        column.addWidget(self.area_filter)
        column.addWidget(self.area_list)
        column.addWidget(self.selection_label)
        column.addWidget(self.clear_selection_button)
        column.addWidget(self.clip_toggle)
        column.addSpacing(6)
        column.addWidget(_section("Colours"))
        column.addWidget(self.classic_toggle)
        column.addLayout(symbology)
        column.addSpacing(6)
        column.addWidget(_section("Legend"))
        column.addWidget(self.legend)
        column.addSpacing(6)
        column.addWidget(_section("Map layers"))
        column.addLayout(layers)
        column.addSpacing(6)
        column.addWidget(_section("Under the pointer"))
        column.addWidget(self.pointer_label)
        column.addSpacing(6)
        column.addWidget(_section("Details"))
        column.addLayout(details)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self._panel = QFrame(objectName="IdwPanel")
        self._panel.setFixedWidth(PANEL_WIDTH)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(scroll)
        self._set_area_enabled(False)

    def _dspin(self, low, high, value, step, suffix) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    def show_view(self, index: int) -> None:
        if index == WORLD and not self.world.available:
            index = PICTURE
        self.views.setCurrentIndex(index)
        (self.world_tab if index == WORLD else self.picture_tab).setChecked(True)
        self.map_hint.setVisible(index == WORLD and self._boundary is not None)

    # ================================================================ opening points
    def open_points(self) -> None:
        start = str(Path(self._layer.path).parent) if self._layer else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open points", start,
                                              "Points (*.shp *.csv);;Shapefiles (*.shp);;CSV tables (*.csv);;"
                                              "All files (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        self.subtitle.setText(Path(path).name)
        self._csv_path = ""
        if path.lower().endswith(".csv"):
            self._open_csv(path)
            return
        self._show_coordinate_columns(False)
        self.banner.show_info("Reading the shapefile…")
        run_task(self, self._facade.load_shapefile, path, on_success=self._on_layer, on_error=self._on_error)

    # ------------------------------------------------------------- a CSV of points
    def _open_csv(self, path: str) -> None:
        """Read the CSV's columns, guess which hold the longitude and latitude, and load its points."""
        try:
            table = self._facade.inspect_points_csv(path)
        except GeeAssistError as exc:
            self._on_error(exc)
            return
        self._csv_path = path
        self._show_coordinate_columns(True)
        for box, guess in ((self.lon_box, table.lon_column), (self.lat_box, table.lat_column)):
            box.blockSignals(True)
            box.clear()
            box.addItem("Choose…", "")
            for name in table.numeric:
                box.addItem(name, name)
            box.setCurrentIndex(max(0, box.findData(guess)))
            box.blockSignals(False)
        if table.lon_column and table.lat_column:
            self._load_csv_points()
        else:
            self._layer = None
            self._set_ready(False)
            self.banner.show_info(f"{table.rows:,} rows. Choose the longitude and latitude columns "
                                  "(in degrees).")

    def _on_coordinate_column(self, *_args) -> None:
        if getattr(self, "_csv_path", "") and self.lon_box.currentData() and self.lat_box.currentData():
            self._load_csv_points()

    def _load_csv_points(self) -> None:
        self.banner.show_info("Reading the CSV…")
        run_task(self, self._facade.load_points_csv, self._csv_path, self.lon_box.currentData(),
                 self.lat_box.currentData(), on_success=self._on_layer, on_error=self._on_error)

    def _show_coordinate_columns(self, visible: bool) -> None:
        for widget in self._coordinate_rows:
            widget.setVisible(visible)

    def _on_layer(self, layer: VectorLayerDTO) -> None:
        if layer.kind not in (POINT, MULTIPOINT):
            self._layer = None
            self._set_ready(False)
            if layer.kind == POLYGON:
                self.banner.show_error("These are areas, not points: open them with “Open boundaries…”, and "
                                       "open measured points with “Open points…”.")
            else:
                self.banner.show_error(f"IDW needs points; this shapefile holds {layer.kind}s. "
                                       "Open a layer of measured points.")
            return
        coordinates = {self.lon_box.currentData(), self.lat_box.currentData()} if self._csv_path else set()
        numeric = [f.name for f in layer.fields if f.type == "number" and f.name not in coordinates]
        if not numeric:
            self._layer = None
            self._set_ready(False)
            self.banner.show_error("This file has no numeric field to interpolate.")
            return
        self._layer = layer
        self.field_box.blockSignals(True)
        self.field_box.clear()
        self.field_box.addItems(numeric)
        self.field_box.setCurrentText(default_value_field(layer, numeric))   # a measurement, not an ID
        self.field_box.blockSignals(False)
        self.detail_labels["points"].setText(f"{layer.feature_count:,}")
        self._set_ready(True)
        self._send_points()
        if self.result is None:
            self.world.fit(layer.bounds)
        self.banner.show_info(f"{layer.feature_count:,} points loaded. Choose a field and press Run IDW.")

    def _send_points(self) -> None:
        if self._layer is None:
            return
        shown = self.shown_points()
        points = [(lon, lat, self._point_tooltip(lon, lat, feature)) for lon, lat, feature in shown]
        self.world.set_points(points)            # skipped by the map when nothing changed
        key = (self.field_box.currentText(), tuple((lon, lat) for lon, lat, _f in shown))
        if key != getattr(self, "_table_key", None):   # rebuild the table only when its rows change
            self._table_key = key
            self._fill_points_table()

    # ------------------------------------------------------------- the points' details
    def point_columns(self) -> list[str]:
        """The table's columns: a CSV's own columns in its order; for a shapefile, the coordinates
        and then its attributes."""
        if self._layer is None:
            return []
        names = [f.name for f in self._layer.fields]
        return names if self._csv_path else ["Longitude", "Latitude"] + names

    def _point_cells(self, lon: float, lat: float, feature) -> list[str]:
        cells = []
        for column in self.point_columns():
            if not self._csv_path and column == "Longitude":
                cells.append(f"{lon:.6f}")
            elif not self._csv_path and column == "Latitude":
                cells.append(f"{lat:.6f}")
            else:
                cells.append(_cell(feature.attributes.get(column)))
        return cells

    def _point_tooltip(self, lon: float, lat: float, feature) -> str:
        """HTML for the point's map tooltip: the value interpolated first, then its other details."""
        field = self.field_box.currentText()
        rows = []
        value = feature.attributes.get(field)
        if field:
            rows.append(f"<b>{_html(field)}: {_html(format_value(value) if isinstance(value, (int, float)) else value)}</b>")
        for column, cell in zip(self.point_columns(), self._point_cells(lon, lat, feature)):
            if column != field and cell != "" and len(rows) < 9:
                rows.append(f"{_html(column)}: {_html(cell)}")
        return "<br>".join(rows)

    def _fill_points_table(self) -> None:
        table = self.points_table
        shown = self.shown_points()
        columns = self.point_columns()
        limit = 20_000
        table.setUpdatesEnabled(False)
        table.clear()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(min(len(shown), limit))
        field = self.field_box.currentText()
        bold_column = columns.index(field) if field in columns else -1
        for row, (lon, lat, feature) in enumerate(shown[:limit]):
            for col, text in enumerate(self._point_cells(lon, lat, feature)):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, (lon, lat))
                if col == bold_column:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                table.setItem(row, col, item)
        if bold_column >= 0:
            header = table.horizontalHeaderItem(bold_column)
            header.setText(f"{field}  ◆")
            header.setToolTip("The value being interpolated")
        table.resizeColumnsToContents()
        table.setUpdatesEnabled(True)
        total = len(self._layer.features) if self._layer else 0
        source = "CSV columns" if self._csv_path else "coordinates and attributes"
        self.points_title.setText(f"SAMPLE POINTS ({len(shown):,})")
        hidden = "" if len(shown) == sum(len(r) for f in (self._layer.features if self._layer else ())
                                         for r in f.parts) else " · only those inside the selected area"
        more = f" · first {limit:,} listed" if len(shown) > limit else ""
        self.points_note.setText(f"{source}{hidden}{more} · click a row to find it on the map" if total else
                                 "Open points to see them here.")

    def _on_point_row(self) -> None:
        rows = self.points_table.selectionModel().selectedRows() if self.points_table.selectionModel() else []
        if not rows:
            return
        item = self.points_table.item(rows[0].row(), 0)
        if item is None:
            return
        lon, lat = item.data(Qt.ItemDataRole.UserRole)
        pad = 0.01
        self.world.fit((lon - pad, lat - pad, lon + pad, lat + pad))
        self.pointer_label.setText(" · ".join(f"{c}: {v}" for c, v in zip(
            self.point_columns(), (self.points_table.item(rows[0].row(), i).text()
                                   for i in range(self.points_table.columnCount()))) if v))

    def shown_points(self) -> list[tuple[float, float, object]]:
        """(lon, lat, feature) of the sample points to draw: all of them, or only those inside the
        selected area when "Points outside the selected area" is off."""
        if self._layer is None:
            return []
        every = [(lon, lat, feature) for feature in self._layer.features for ring in feature.parts for lon, lat in ring]
        if self.focus_toggles["outside_points"].isChecked() or not self.selected or self._boundary is None:
            return every
        polygons = polygons_of(self._boundary, self.selected)
        if not every or not polygons:
            return every
        inside = _in_polygons(np.array([p[0] for p in every]), np.array([p[1] for p in every]), polygons)
        return [point for point, keep in zip(every, inside) if keep]

    def _points_changed(self) -> None:
        """The points to draw changed (a toggle or the selection): redraw them on the map and picture."""
        self._send_points()
        if self.result is not None and self._rgba is not None:
            self.picture.set_image(rgba_to_image(self._with_points(self._rgba)), self.result.bounds,
                                   self.result.width, keep_view=True)

    def _on_other_areas(self, on: bool) -> None:
        self.world.set_other_areas_visible(on)

    # ================================================================ boundaries and the selection
    def open_boundaries(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open boundaries", "", "Shapefiles (*.shp);;All files (*)")
        if path:
            self.load_boundaries(path)

    def load_boundaries(self, path: str) -> None:
        self.banner.show_info("Reading the boundaries…")
        run_task(self, self._facade.load_shapefile, path, on_success=self._on_boundaries, on_error=self._on_error)

    def _on_boundaries(self, layer: VectorLayerDTO) -> None:
        if layer.kind != POLYGON:
            self.banner.show_error(f"Boundaries must be areas (polygons); this shapefile holds {layer.kind}s.")
            return
        self._boundary = layer
        self.selected = set()
        self.name_box.blockSignals(True)
        self.name_box.clear()
        self.name_box.addItems([f.name for f in layer.fields])
        self.name_box.setCurrentText(label_field_of(layer))
        self.name_box.blockSignals(False)
        self._fill_areas()
        self.world.set_boundaries(boundaries_geojson(layer, self.name_box.currentText()))
        self.world.set_layer_visible("boundaries", self.layer_toggles["boundaries"].isChecked())
        if self.result is None and self._layer is None:
            self.world.fit(layer.bounds)
        self._set_area_enabled(True)
        self.show_view(self.views.currentIndex())
        self._update_selection_label()
        self.banner.show_info(f"{layer.feature_count:,} areas from {Path(layer.path).name}. Ctrl+click areas on "
                              "the map (or tick them in the list) to interpolate within them.")

    def _area_name(self, index: int) -> str:
        return area_label(self._boundary, index, self.name_box.currentText())

    def _fill_areas(self) -> None:
        self.area_list.blockSignals(True)
        self.area_list.clear()
        if self._boundary is not None:
            for index in range(len(self._boundary.features)):
                item = QListWidgetItem(self._area_name(index))
                item.setToolTip(item.text())
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if index in self.selected else Qt.CheckState.Unchecked)
                self.area_list.addItem(item)
        self.area_list.blockSignals(False)
        self._filter_areas(self.area_filter.text())

    def _on_name_field(self, *_args) -> None:
        if self._boundary is None:
            return
        self._fill_areas()
        self.world.set_boundaries(boundaries_geojson(self._boundary, self.name_box.currentText()))
        self.world.set_selection(self.selected)
        self._update_selection_label()

    def _filter_areas(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.area_list.count()):
            item = self.area_list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _on_area_ticked(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        chosen = set(self.selected)
        if item.checkState() == Qt.CheckState.Checked:
            chosen.add(index)
        else:
            chosen.discard(index)
        self.set_selection(chosen)

    def toggle_area(self, index: int) -> None:
        """Ctrl+click on area ``index`` of the map: select it, or deselect it if it was selected."""
        if self._boundary is None or not 0 <= index < len(self._boundary.features):
            return
        self.set_selection(self.selected ^ {index})

    def set_selection(self, indices: set[int]) -> None:
        self.selected = set(indices)
        self.area_list.blockSignals(True)
        for row in range(self.area_list.count()):
            item = self.area_list.item(row)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in self.selected
                               else Qt.CheckState.Unchecked)
        self.area_list.blockSignals(False)
        self.world.set_selection(self.selected)
        self._update_selection_label()
        self._points_changed()

    def selected_names(self) -> list[str]:
        return [self._area_name(i) for i in sorted(self.selected)] if self._boundary is not None else []

    def _update_selection_label(self) -> None:
        if self._boundary is None:
            return
        names = self.selected_names()
        if not names:
            self.selection_label.setText("No area selected: the surface covers the points. Ctrl+click areas on the "
                                         "map (or tick them) to interpolate within them.")
        else:
            shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
            self.selection_label.setText(f"Selected: {shown}. The next run covers "
                                         f"{'it' if len(names) == 1 else 'them'}.")
        self.clear_selection_button.setEnabled(bool(names))
        self.clip_toggle.setEnabled(bool(names))
        for toggle in self.focus_toggles.values():
            toggle.setEnabled(bool(names))

    def _set_area_enabled(self, on: bool) -> None:
        for widget in (self.name_box, self.area_filter, self.area_list):
            widget.setEnabled(on)
        self.clear_selection_button.setEnabled(on and bool(self.selected))
        self.clip_toggle.setEnabled(on and bool(self.selected))
        for toggle in self.focus_toggles.values():
            toggle.setEnabled(on and bool(self.selected))

    # ================================================================ running
    def run(self) -> None:
        if self._layer is None or self.field_box.currentText() == "":
            return
        field = self.field_box.currentText()
        points = self._sample_points(field)
        if len(points) < 2:
            self.banner.show_error(f"Fewer than two points have a numeric {field}.")
            return
        boundary = polygons_of(self._boundary, self.selected) if self._boundary is not None and self.selected else ()
        params = IDWParamsDTO(power=self.power.value(), neighbours=self.neighbours.value(),
                              radius=self.radius.value(), resolution=self.resolution.value(),
                              boundary=boundary, clip_to_boundary=self.clip_toggle.isChecked())
        where = f" within {', '.join(self.selected_names()[:3])}" if boundary else ""
        self.banner.show_info(f"Interpolating{where}…")
        run_task(self, self._facade.interpolate_idw, points, field, params,
                 on_success=self._on_surface, on_error=self._on_error)

    def _sample_points(self, field: str) -> list[SamplePointDTO]:
        points: list[SamplePointDTO] = []
        for feature in self._layer.features:
            value = feature.attributes.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            for ring in feature.parts:
                for lon, lat in ring:
                    points.append(SamplePointDTO(lon=lon, lat=lat, value=float(value)))
        return points

    def _on_surface(self, result: IDWResultDTO) -> None:
        self.result = result
        self.recolour(fit=True)
        self.banner.show_info(" ".join(result.notes)) if result.notes else self.banner.clear()
        self.save_button.setEnabled(True)
        self.pdf_button.setEnabled(True)
        self.fit_button.setEnabled(True)
        minx, miny, maxx, maxy = result.bounds
        self.detail_labels["field"].setText(result.field)
        self.detail_labels["range"].setText(f"{result.stats['min']:.3g} to {result.stats['max']:.3g}"
                                             f"  (mean {result.stats['mean']:.3g})")
        self.detail_labels["cell"].setText(f"{result.cell_size[0]:.4g} × {result.cell_size[1]:.4g}°")
        self.detail_labels["extent"].setText(f"{miny:.4f} to {maxy:.4f}\n{minx:.4f} to {maxx:.4f}")
        self._send_points()
        self.surface_ready.emit(result)

    # ================================================================ colours and the legend
    def ramp(self) -> str:
        return idw_colours.CLASSIC if self.classic_toggle.isChecked() else idw_colours.VIRIDIS

    def recolour(self, fit: bool = False) -> None:
        """Colour the surface (ramp, classes) and refresh the map, the picture and the legends."""
        if self.result is None:
            return
        method = self.method_box.currentData()
        self.classes.setEnabled(method != idw_colours.CONTINUOUS)
        rgba, legend = idw_colours.render(self.result.values, self.ramp(), method, self.classes.value())
        self._rgba = rgba
        title = f"{self.result.field} (IDW)"
        colours = idw_colours.stops(self.ramp())
        if legend[0] == "scale":
            self._legend = ("scale", colours, legend[1], legend[2])
            self.legend.set_legend(LegendDTO("scale", title, low=legend[1], high=legend[2], colours=colours))
            self.map_legend.show_scale(title, colours, legend[1], (legend[1] + legend[2]) / 2, legend[2])
            self.picture.show_legend_scale(title, colours, legend[1], legend[2])
        else:
            rows = legend[1]
            self._legend = ("classes", rows)
            self.legend.set_legend(LegendDTO("classes", title, colours=tuple(c for _l, c in rows),
                                             labels=tuple(label for label, _c in rows)))
            self.map_legend.show_classes(title, rows)
            self.picture.show_legend_classes(title, rows)
        self._place_map_overlays()
        self.picture.set_image(rgba_to_image(self._with_points(rgba)), self.result.bounds, self.result.width,
                               keep_view=not fit)
        self.world.set_surface(_png(rgba), self.result.bounds, self.opacity.value() / 100)
        if fit:
            self.world.fit(self.result.bounds)

    def _with_points(self, rgba: np.ndarray) -> np.ndarray:
        """The surface with the sample points dotted on (the picture view has no points layer)."""
        out = rgba.copy()
        if self._layer is None or self.result is None:
            return out
        west, south, east, north = self.result.bounds
        h, w = out.shape[:2]
        for lon, lat, _feature in self.shown_points():
            col = int((lon - west) / (east - west) * w)
            row = int((north - lat) / (north - south) * h)
            if 0 <= row < h and 0 <= col < w:
                out[max(0, row - 1):row + 2, max(0, col - 1):col + 2] = (20, 20, 20, 255)
                out[row, col] = (255, 255, 255, 255)
        return out

    def _place_map_overlays(self) -> None:
        margin = 12
        if self.map_legend.isVisible():
            self.map_legend.adjustSize()
            self.map_legend.move(margin, self.world.height() - self.map_legend.height() - margin - 18)
            self.map_legend.raise_()
        if self.map_readout.isVisible():
            self.map_readout.adjustSize()
            self.map_readout.move(self.world.width() - self.map_readout.width() - margin, margin + 40)
            self.map_readout.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._place_map_overlays()

    def fit(self) -> None:
        bounds = self.result.bounds if self.result else (self._layer.bounds if self._layer else None)
        if bounds is not None:
            self.world.fit(bounds)
        self.canvas.fit()

    # ================================================================ saving and the PDF
    def save_surface(self) -> None:
        if self.result is None:
            return
        suggested = f"idw_{self.result.field}.tif"
        path, _ = QFileDialog.getSaveFileName(self, "Save surface", suggested, "GeoTIFF (*.tif)")
        if path:
            run_task(self, self._facade.save_interpolation, self.result, path,
                     on_success=self._on_saved, on_error=self._on_error)

    def _on_saved(self, path: str) -> None:
        self.banner.show_info(f"Saved to {path}")

    def layout_spec(self):
        """What the PDF designer needs: the coloured surface, its legend, boundaries and points."""
        from frontend.views.map_layout_dialog import MapLayoutSpec

        result = self.result
        west, south, east, north = result.bounds
        rings, selected = [], []
        if self._boundary is not None:
            for index, feature in enumerate(self._boundary.features):
                fx0, fy0, fx1, fy1 = feature.bounds
                if fx1 < west or fx0 > east or fy1 < south or fy0 > north:
                    continue   # far outside the map
                if index not in self.selected and self.selected and \
                        not self.focus_toggles["other_areas"].isChecked():
                    continue   # only the selected area, as on the map
                target = selected if index in self.selected else rings
                target.extend(list(ring) for ring in feature.parts if len(ring) >= 2)
        points = [(lon, lat) for lon, lat, _feature in self.shown_points()]
        where = f" — {', '.join(self.selected_names()[:3])}" if self.selected else ""
        note = " ".join(result.notes)

        def load_boundary(path: str):
            layer = self._facade.load_shapefile(path)
            return [list(ring) for feature in layer.features for ring in feature.parts if len(ring) >= 2]

        return MapLayoutSpec(
            title=f"{result.field} (IDW){where}", image=rgba_to_image(self._rgba), extent=result.bounds,
            geographic=True, legend_title=f"{result.field}", legend=self._legend, boundary_rings=rings + selected,
            selected_rings=selected, points=points, note=note, load_boundary=load_boundary)

    def export_pdf(self) -> None:
        if self.result is None:
            return
        from frontend.views.map_layout_dialog import MapLayoutDialog

        dialog = MapLayoutDialog(self.layout_spec(), self)
        dialog.exec()
        if dialog.exported:
            self.banner.show_info(f"Map exported to {dialog.exported}")

    def _on_error(self, exc: Exception) -> None:
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "The surface could not be made.")

    # ================================================================ the value under the pointer
    def _value_at_pixel(self, x: int, y: int):
        if self.result is None:
            return None
        values = self.result.values
        if not (0 <= y < values.shape[0] and 0 <= x < values.shape[1]):
            return None
        value = values[y, x]
        return ("no estimate" if not np.isfinite(value) else format_value(float(value)), self.result.field)

    def _on_world_pointer(self, lon: float, lat: float) -> None:
        if self.result is None:
            return
        west, south, east, north = self.result.bounds
        x = (lon - west) / (east - west) * self.result.width
        y = (north - lat) / (north - south) * self.result.height
        self._on_hovered(x, y)
        reading = self._value_at_pixel(int(x), int(y))
        if reading is None:
            self.map_readout.hide()
            return
        self.map_readout.show_value(reading[0], reading[1], lon, lat)
        self._place_map_overlays()

    def _on_hovered(self, x: float, y: float) -> None:
        self._pointer = (x, y)
        self._hover_timer.start()

    def _on_left(self) -> None:
        self._pointer = None
        self._hover_timer.stop()
        self.map_readout.hide()
        self.pointer_label.setText("Run IDW, then point at the surface to read a value.")

    def _read_value(self) -> None:
        if self._pointer is None or self.result is None:
            return
        x, y = self._pointer
        values = self.result.values
        col = min(values.shape[1] - 1, max(0, int(x)))
        row = min(values.shape[0] - 1, max(0, int(y)))
        formatted = format_value(values[row, col])  # NaN (unestimated cell) -> "no data"
        text = "no estimate" if formatted == "no data" else formatted
        self.pointer_label.setText(f"{self.result.field}: {text}")

    def _open_folder(self) -> None:
        if self._layer is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._layer.path).parent)))

    def _set_ready(self, ready: bool) -> None:
        for widget in (self.field_box, self.power, self.neighbours, self.radius, self.resolution, self.run_button):
            widget.setEnabled(ready)
        self.fit_button.setEnabled(ready or self.result is not None)
        self.folder_button.setEnabled(self._layer is not None)
        if not ready:
            self.save_button.setEnabled(False)
            self.pdf_button.setEnabled(False)


def _png(rgba: np.ndarray) -> bytes:
    image = rgba_to_image(rgba)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def _in_polygons(lons: np.ndarray, lats: np.ndarray, polygons) -> np.ndarray:
    """True for each point inside any of ``polygons`` (each: outer ring, then holes)."""
    inside = np.zeros(lons.shape, dtype=bool)
    for polygon in polygons:
        if not polygon:
            continue
        hit = _ray_cast(lons, lats, polygon[0])
        for hole in polygon[1:]:
            hit &= ~_ray_cast(lons, lats, hole)
        inside |= hit
    return inside


def _ray_cast(x: np.ndarray, y: np.ndarray, ring) -> np.ndarray:
    """Point-in-polygon (ray casting) for many points against one ring."""
    ring = np.asarray(ring, dtype="float64")
    if len(ring) < 3:
        return np.zeros(x.shape, dtype=bool)
    xi, yi = ring[:, 0], ring[:, 1]
    xj, yj = np.roll(xi, 1), np.roll(yi, 1)
    crossing = (yi[None, :] > y[:, None]) != (yj[None, :] > y[:, None])
    with np.errstate(divide="ignore", invalid="ignore"):
        at = (xj - xi)[None, :] * (y[:, None] - yi[None, :]) / (yj - yi)[None, :] + xi[None, :]
    return (np.count_nonzero(crossing & (x[:, None] < at), axis=1) % 2).astype(bool)


def _html(value) -> str:
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell(value) -> str:
    """A table cell: whole numbers without ".0", others in full (coordinates keep their decimals)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


_ID_NAME = re.compile(r"(^|[_\s-])(id|fid|oid|gid|uid|objectid|index|idx|no|num|number|sr|sno|srno|serial|code|"
                      r"rank|row|seq|key)$|^(id|fid|objectid|sr|sno|serial)[_\s-]?", re.IGNORECASE)


def looks_like_identifier(layer, field: str) -> bool:
    """A column that numbers the points rather than measuring something: named like an ID
    (Sample_ID, FID, OBJECTID, Sr_No…) or holding distinct whole numbers (1, 2, 3…)."""
    if _ID_NAME.search(field.strip()):
        return True
    values = [f.attributes.get(field) for f in layer.features]
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(values) < 3 or any(float(v) != int(v) for v in values):
        return False
    ordered = sorted(int(v) for v in values)
    distinct = len(set(ordered)) == len(ordered)
    consecutive = ordered[-1] - ordered[0] == len(ordered) - 1
    return distinct and consecutive


def default_value_field(layer, numeric: list[str]) -> str:
    """The field to interpolate by default: the first that is not an ID (else the first)."""
    for field in numeric:
        if not looks_like_identifier(layer, field):
            return field
    return numeric[0] if numeric else ""
