"""IDW Interpolation page: turn point measurements into a continuous surface.

Open a point shapefile or a CSV of points (longitude and latitude columns in degrees),
pick the numeric field to interpolate (e.g. rainfall, temperature,
elevation at wells), set the IDW parameters (power, number of neighbours, search radius,
output resolution) and run. The surface is drawn with a colour ramp and the sample points
are dotted on top, as ArcGIS's IDW tool shows them. "Save surface…" writes it as a GeoTIFF.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.interpolation_dto import IDWParamsDTO, IDWResultDTO, SamplePointDTO
from backend.dto.vector_dto import MULTIPOINT, POINT, VectorLayerDTO
from backend.exceptions import GeeAssistError
from frontend import theme, theming
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.raster_canvas import RasterCanvas, rgba_to_image
from frontend.widgets.raster_legend import RasterLegend, format_value
from frontend.workers.task_worker import run_task

PANEL_WIDTH = 320
HOVER_DELAY_MS = 40

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
QComboBox, QDoubleSpinBox, QSpinBox {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px;
    padding: 5px 8px; color: {theme.INK};
}}
"""


def _section(title: str) -> QLabel:
    return QLabel(title.upper(), objectName="SectionTitle")


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

        self.title = QLabel("IDW Interpolation", objectName="PageTitle")
        self.subtitle = QLabel("Open a point shapefile or a CSV of points and interpolate one of its numeric "
                               "fields.",
                               objectName="PageSubtitle")
        self.banner = StatusBanner()

        self.open_button = QPushButton("Open points…", objectName="PrimaryButton")
        self.run_button = QPushButton("Run IDW", objectName="PrimaryButton")
        self.save_button = QPushButton("Save surface…", objectName="SecondaryButton")
        self.fit_button = QPushButton("Fit to window", objectName="SecondaryButton")
        self.folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for button in (self.open_button, self.run_button, self.save_button, self.fit_button, self.folder_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            toolbar.addWidget(button)
        toolbar.addStretch(1)

        self.canvas = RasterCanvas()
        canvas_card = QFrame(objectName="IdwCanvasCard")
        canvas_layout = QVBoxLayout(canvas_card)
        canvas_layout.setContentsMargins(6, 6, 6, 6)
        canvas_layout.addWidget(self.canvas)

        self._build_panel()

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(canvas_card, 1)
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
        self.run_button.clicked.connect(self.run)
        self.save_button.clicked.connect(self.save_surface)
        self.fit_button.clicked.connect(self.canvas.fit)
        self.folder_button.clicked.connect(self._open_folder)
        self.canvas.hovered.connect(self._on_hovered)
        self.canvas.left_image.connect(self._on_left)
        self._set_ready(False)

    def _build_panel(self) -> None:
        self.field_box = QComboBox()
        self.field_box.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._show_coordinate_columns(False)
        params.setColumnStretch(1, 1)

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
        column.setSpacing(10)
        column.addWidget(_section("Interpolation"))
        column.addLayout(params)
        column.addSpacing(6)
        column.addWidget(self.legend)
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

    def _dspin(self, low, high, value, step, suffix) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    # ------------------------------------------------------------- opening points
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
            self.banner.show_error("IDW needs points; this shapefile holds "
                                   f"{layer.kind}s. Open a layer of measured points.")
            return
        coordinates = {self.lon_box.currentData(), self.lat_box.currentData()} if self._csv_path else set()
        numeric = [f.name for f in layer.fields if f.type == "number" and f.name not in coordinates]
        if not numeric:
            self._layer = None
            self._set_ready(False)
            self.banner.show_error("This shapefile has no numeric field to interpolate.")
            return
        self._layer = layer
        self.field_box.clear()
        self.field_box.addItems(numeric)
        self.detail_labels["points"].setText(f"{layer.feature_count:,}")
        self._set_ready(True)
        self.banner.show_info(f"{layer.feature_count:,} points loaded. Choose a field and press Run IDW.")

    # ------------------------------------------------------------- running
    def run(self) -> None:
        if self._layer is None or self.field_box.currentText() == "":
            return
        field = self.field_box.currentText()
        points = self._sample_points(field)
        if len(points) < 2:
            self.banner.show_error(f"Fewer than two points have a numeric {field}.")
            return
        params = IDWParamsDTO(power=self.power.value(), neighbours=self.neighbours.value(),
                              radius=self.radius.value(), resolution=self.resolution.value())
        self.banner.show_info("Interpolating…")
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
        same = self.result is not None and (self.result.width, self.result.height) == (result.width, result.height)
        self.result = result
        self.canvas.set_image(rgba_to_image(result.rgba), keep_view=same)
        self.legend.set_legend(result.legend)
        self.banner.show_info(" ".join(result.notes)) if result.notes else self.banner.clear()
        self.save_button.setEnabled(True)
        minx, miny, maxx, maxy = result.bounds
        self.detail_labels["field"].setText(result.field)
        self.detail_labels["range"].setText(f"{result.stats['min']:.3g} to {result.stats['max']:.3g}"
                                             f"  (mean {result.stats['mean']:.3g})")
        self.detail_labels["cell"].setText(f"{result.cell_size[0]:.4g} × {result.cell_size[1]:.4g}°")
        self.detail_labels["extent"].setText(f"{miny:.4f} to {maxy:.4f}\n{minx:.4f} to {maxx:.4f}")
        self.surface_ready.emit(result)

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

    def _on_error(self, exc: Exception) -> None:
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "The surface could not be made.")

    # ------------------------------------------------------------- pointer
    def _on_hovered(self, x: float, y: float) -> None:
        self._pointer = (x, y)
        self._hover_timer.start()

    def _on_left(self) -> None:
        self._pointer = None
        self._hover_timer.stop()
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
        self.fit_button.setEnabled(ready and self.result is not None)
        self.folder_button.setEnabled(self._layer is not None)
        if not ready:
            self.save_button.setEnabled(False)
