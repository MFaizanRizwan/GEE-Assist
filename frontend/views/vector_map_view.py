"""Vector Maps page: open an ESRI shapefile and explore it on a desktop-GIS canvas.

The ``.shp`` is read in the background and reprojected to latitude/longitude, then drawn on
a pan/zoom canvas. The right panel shows the layer's details, lets the user recolour it
(fill, outline, point size), and identifies the feature under the pointer. An attribute
table below the canvas lists every feature; selecting a row highlights it on the map, and
clicking the map selects its row — the two stay in step.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QColorDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.vector_dto import POINT, POLYGON, VectorLayerDTO
from backend.exceptions import GeeAssistError
from frontend import theme, theming
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.vector_canvas import VectorCanvas
from frontend.workers.task_worker import run_task

PANEL_WIDTH = 300

def _stylesheet():
    return f"""
#VectorPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#VectorCanvasCard, QFrame#VectorPanel, QFrame#VectorTableCard {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px;
}}
QFrame#VectorPanel QLabel {{ background: transparent; }}
QLabel#SectionTitle {{ color: {theme.MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#Value {{ color: {theme.INK}; }}
QPushButton#Swatch {{ border: 1px solid {theme.BORDER_STRONG}; border-radius: 6px; min-height: 22px; }}
QTableWidget {{
    background: {theme.WHITE}; border: none; gridline-color: {theme.BORDER};
    color: {theme.INK}; selection-background-color: {theme.MINT}; selection-color: {theme.INK};
}}
QHeaderView::section {{
    background: {theme.FIELD_BG}; color: {theme.MUTED}; border: none;
    border-bottom: 1px solid {theme.BORDER}; padding: 5px 8px; font-weight: 600;
}}
"""

_KIND_LABEL = {"point": "Points", "multipoint": "Multipoints", "polyline": "Lines", "polygon": "Polygons"}


def _section(title: str) -> QLabel:
    return QLabel(title.upper(), objectName="SectionTitle")


class VectorMapView(QWidget):
    layer_loaded = pyqtSignal(object)  # the VectorLayerDTO, after a shapefile opens (for tests/hooks)

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("VectorPage")
        theming.styled(self, _stylesheet)
        self._facade = facade
        self._layer: VectorLayerDTO | None = None
        self._fill = QColor(theme.OCEAN)
        self._outline = QColor(theme.OCEAN)

        # ---- header
        self.title = QLabel("Vector Maps", objectName="PageTitle")
        self.subtitle = QLabel("Open a shapefile (.shp) to see its features on the map.", objectName="PageSubtitle")
        self.banner = StatusBanner()

        # ---- toolbar
        self.open_button = QPushButton("Open shapefile…", objectName="PrimaryButton")
        self.fit_button = QPushButton("Fit to window", objectName="SecondaryButton")
        self.zoom_button = QPushButton("Zoom to selected", objectName="SecondaryButton")
        self.folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        for button in (self.open_button, self.fit_button, self.zoom_button, self.folder_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.fit_button)
        toolbar.addWidget(self.zoom_button)
        toolbar.addWidget(self.folder_button)
        toolbar.addStretch(1)

        # ---- canvas
        self.canvas = VectorCanvas()
        canvas_card = QFrame(objectName="VectorCanvasCard")
        canvas_layout = QVBoxLayout(canvas_card)
        canvas_layout.setContentsMargins(6, 6, 6, 6)
        canvas_layout.addWidget(self.canvas)

        # ---- attribute table
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        table_card = QFrame(objectName="VectorTableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(8, 8, 8, 8)
        table_layout.addWidget(QLabel("Attribute table", objectName="SectionTitle"))
        table_layout.addWidget(self.table)

        centre = QSplitter(Qt.Orientation.Vertical)
        centre.addWidget(canvas_card)
        centre.addWidget(table_card)
        centre.setStretchFactor(0, 3)
        centre.setStretchFactor(1, 1)
        centre.setChildrenCollapsible(False)

        # ---- right panel
        self._build_panel()

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(centre, 1)
        body.addWidget(self._panel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addLayout(toolbar)
        layout.addWidget(self.banner)
        layout.addLayout(body, 1)

        # ---- wiring
        self.open_button.clicked.connect(self.open_shapefile)
        self.fit_button.clicked.connect(self.canvas.fit)
        self.zoom_button.clicked.connect(self._zoom_to_selected)
        self.folder_button.clicked.connect(self._open_folder)
        self.canvas.feature_clicked.connect(self._on_feature_picked)
        self.canvas.feature_hovered.connect(self._on_feature_hovered)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.fill_swatch.clicked.connect(lambda: self._pick_colour("fill"))
        self.outline_swatch.clicked.connect(lambda: self._pick_colour("outline"))
        self.point_size.valueChanged.connect(self.canvas.set_point_size)
        self._set_ready(False)
        self._refresh_swatches()

    # ------------------------------------------------------------- panel
    def _build_panel(self) -> None:
        self.detail_labels: dict[str, QLabel] = {}
        details = QGridLayout()
        details.setHorizontalSpacing(12)
        details.setVerticalSpacing(4)
        for row, (key, name) in enumerate((("name", "Layer"), ("kind", "Geometry"), ("features", "Features"),
                                           ("crs", "Coordinates"), ("extent", "Extent"), ("fields", "Fields"))):
            value = QLabel("–", objectName="Value")
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.addWidget(QLabel(name, objectName="Muted"), row, 0, Qt.AlignmentFlag.AlignTop)
            details.addWidget(value, row, 1)
            self.detail_labels[key] = value
        details.setColumnStretch(1, 1)

        self.fill_swatch = QPushButton(objectName="Swatch")
        self.fill_swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.outline_swatch = QPushButton(objectName="Swatch")
        self.outline_swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.point_size = QSpinBox()
        self.point_size.setRange(2, 30)
        self.point_size.setValue(7)
        self.point_size.setSuffix(" px")
        symbology = QGridLayout()
        symbology.setHorizontalSpacing(12)
        symbology.setVerticalSpacing(6)
        symbology.addWidget(QLabel("Fill", objectName="Muted"), 0, 0)
        symbology.addWidget(self.fill_swatch, 0, 1)
        symbology.addWidget(QLabel("Outline", objectName="Muted"), 1, 0)
        symbology.addWidget(self.outline_swatch, 1, 1)
        self._point_row = (QLabel("Point size", objectName="Muted"), self.point_size)
        symbology.addWidget(self._point_row[0], 2, 0)
        symbology.addWidget(self._point_row[1], 2, 1)
        symbology.setColumnStretch(1, 1)

        self.identify_label = QLabel("Point at a feature, or click it, to see its attributes.", objectName="Muted")
        self.identify_label.setWordWrap(True)
        self.identify_grid = QGridLayout()
        self.identify_grid.setHorizontalSpacing(12)
        self.identify_grid.setVerticalSpacing(3)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(10)
        column.addWidget(_section("Layer"))
        column.addLayout(details)
        column.addSpacing(6)
        column.addWidget(_section("Symbology"))
        column.addLayout(symbology)
        column.addSpacing(6)
        column.addWidget(_section("Identify"))
        column.addWidget(self.identify_label)
        column.addLayout(self.identify_grid)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self._panel = QFrame(objectName="VectorPanel")
        self._panel.setFixedWidth(PANEL_WIDTH)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(scroll)

    # ------------------------------------------------------------- opening
    def open_shapefile(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        start = str(Path(self._layer.path).parent) if self._layer else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open shapefile", start, "Shapefiles (*.shp);;All files (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        """Read the shapefile at ``path`` in the background and show it."""
        self.subtitle.setText(Path(path).name)
        self._set_ready(False)
        self.banner.show_info("Reading the shapefile…")
        run_task(self, self._facade.load_shapefile, path, on_success=self._on_loaded, on_error=self._on_error)

    def _on_loaded(self, layer: VectorLayerDTO) -> None:
        self._layer = layer
        self.canvas.set_layer(layer)
        self._fill_details(layer)
        self._fill_table(layer)
        self._clear_identify()
        self._point_row[0].setVisible(layer.kind in (POINT, "multipoint"))
        self._point_row[1].setVisible(layer.kind in (POINT, "multipoint"))
        self._set_ready(True)
        count = layer.feature_count
        self.banner.show_info(f"{count:,} {_KIND_LABEL.get(layer.kind, 'features').lower()} loaded.")
        self.subtitle.setText(f"{layer.name}  ·  {_KIND_LABEL.get(layer.kind, layer.kind)}  ·  {count:,} features")
        self.layer_loaded.emit(layer)

    def _on_error(self, exc: Exception) -> None:
        self._layer = None
        self.canvas.set_layer(None)
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._set_ready(False)
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "The shapefile could not be opened.")

    # ------------------------------------------------------------- details & table
    def _fill_details(self, layer: VectorLayerDTO) -> None:
        minx, miny, maxx, maxy = layer.bounds
        field_names = ", ".join(f.name for f in layer.fields) or "none"
        texts = {
            "name": layer.name,
            "kind": _KIND_LABEL.get(layer.kind, layer.kind),
            "features": f"{layer.feature_count:,}",
            "crs": layer.crs,
            "extent": f"{miny:.4f}° to {maxy:.4f}° N\n{minx:.4f}° to {maxx:.4f}° E",
            "fields": field_names,
        }
        for key, text in texts.items():
            self.detail_labels[key].setText(text)

    def _fill_table(self, layer: VectorLayerDTO) -> None:
        self.table.blockSignals(True)
        headers = [f.name for f in layer.fields] or ["(no attributes)"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(layer.feature_count)
        for row, feature in enumerate(layer.features):
            for col, field in enumerate(layer.fields):
                value = feature.attributes.get(field.name, "")
                item = QTableWidgetItem("" if value is None else str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.blockSignals(False)

    # ------------------------------------------------------------- selection sync
    def _on_feature_picked(self, index: int) -> None:
        self.table.blockSignals(True)
        if index < 0:
            self.table.clearSelection()
        else:
            self.table.selectRow(index)
            self.table.scrollToItem(self.table.item(index, 0))
        self.table.blockSignals(False)
        self._show_identify(index)

    def _on_feature_hovered(self, index: int) -> None:
        if index >= 0:
            self._show_identify(index)
        elif self.canvas.selected() >= 0:
            self._show_identify(self.canvas.selected())
        else:
            self._clear_identify()

    def _on_row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        index = rows[0].row()
        self.canvas.set_selected(index)
        self._show_identify(index)

    def _zoom_to_selected(self) -> None:
        index = self.canvas.selected()
        if index >= 0:
            self.canvas.zoom_to_feature(index)
        else:
            self.banner.show_info("Select a feature first (click it on the map or in the table).")

    def _show_identify(self, index: int) -> None:
        while self.identify_grid.count():
            item = self.identify_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if self._layer is None or not (0 <= index < len(self._layer.features)):
            self._clear_identify()
            return
        self.identify_label.setText(f"Feature {index + 1} of {self._layer.feature_count}")
        attributes = self._layer.features[index].attributes
        if not attributes:
            return
        for row, (name, value) in enumerate(attributes.items()):
            self.identify_grid.addWidget(QLabel(name, objectName="Muted"), row, 0, Qt.AlignmentFlag.AlignTop)
            field_value = QLabel("" if value is None else str(value), objectName="Value")
            field_value.setWordWrap(True)
            field_value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            field_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.identify_grid.addWidget(field_value, row, 1)
        self.identify_grid.setColumnStretch(1, 1)

    def _clear_identify(self) -> None:
        while self.identify_grid.count():
            item = self.identify_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.identify_label.setText("Point at a feature, or click it, to see its attributes.")

    # ------------------------------------------------------------- symbology
    def _pick_colour(self, which: str) -> None:
        current = self._fill if which == "fill" else self._outline
        chosen = QColorDialog.getColor(current, self, "Choose a colour",
                                       QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not chosen.isValid():
            return
        if which == "fill":
            self._fill = chosen
        else:
            self._outline = chosen
        self.canvas.set_colours(self._fill, self._outline)
        self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        for swatch, colour in ((self.fill_swatch, self._fill), (self.outline_swatch, self._outline)):
            swatch.setStyleSheet(f"#Swatch {{ background: {colour.name()}; border: 1px solid {theme.BORDER_STRONG};"
                                 f" border-radius: 6px; min-height: 22px; }}")

    # ------------------------------------------------------------- misc
    def _open_folder(self) -> None:
        if self._layer is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._layer.path).parent)))

    def _set_ready(self, ready: bool) -> None:
        for button in (self.fit_button, self.zoom_button, self.folder_button):
            button.setEnabled(ready)
