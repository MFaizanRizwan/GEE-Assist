"""Digital Elevation Model page: open a DEM GeoTIFF and derive terrain surfaces.

Choose a surface — elevation (shaded relief), hillshade, slope, aspect or contours — and it
is drawn on a zoom/pan canvas with a legend, as ArcGIS's Spatial Analyst does. Hillshade has
sun azimuth and altitude, contours have an interval, and a vertical exaggeration (z-factor)
applies to the shaded surfaces. "Save surface…" writes the current surface as a GeoTIFF at the
DEM's full resolution. The elevation under the pointer is shown as the mouse moves.
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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.business.terrain import PRODUCTS
from backend.dto.terrain_dto import TerrainInfoDTO, TerrainProductDTO
from backend.exceptions import GeeAssistError
from frontend import theme, theming
from frontend.download_format import format_size
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.raster_canvas import RasterCanvas, rgba_to_image
from frontend.widgets.raster_legend import RasterLegend, format_value
from frontend.workers.task_worker import run_task

PANEL_WIDTH = 320
HOVER_DELAY_MS = 40

def _stylesheet():
    return f"""
#DemPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20.6pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#DemCanvasCard, QFrame#DemPanel {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px;
}}
QFrame#DemPanel QLabel {{ background: transparent; }}
QLabel#SectionTitle {{ color: {theme.MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#Value {{ color: {theme.INK}; }}
QComboBox, QDoubleSpinBox {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px;
    padding: 5px 8px; color: {theme.INK};
}}
"""


def _section(title: str) -> QLabel:
    return QLabel(title.upper(), objectName="SectionTitle")


class DemView(QWidget):
    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DemPage")
        theming.styled(self, _stylesheet)
        self._facade = facade
        self.info: TerrainInfoDTO | None = None
        self.product: TerrainProductDTO | None = None
        self._pointer: tuple[float, float] | None = None

        self.title = QLabel("Digital Elevation Model", objectName="PageTitle")
        self.subtitle = QLabel("Open a DEM GeoTIFF to derive hillshade, slope, aspect and contours.",
                               objectName="PageSubtitle")
        self.banner = StatusBanner()

        self.open_button = QPushButton("Open DEM…", objectName="PrimaryButton")
        self.save_button = QPushButton("Save surface…", objectName="SecondaryButton")
        self.fit_button = QPushButton("Fit to window", objectName="SecondaryButton")
        self.folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        self.pdf_button = QPushButton("Export PDF…", objectName="SecondaryButton")
        self.pdf_button.setToolTip("Lay out a printable map: title, north arrow, scale bar, legend and a "
                                   "boundary layer of your choice")
        self.pdf_button.setEnabled(False)
        self.pdf_button.clicked.connect(self.export_pdf)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for button in (self.open_button, self.save_button, self.pdf_button, self.fit_button, self.folder_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            toolbar.addWidget(button)
        toolbar.addStretch(1)

        self.canvas = RasterCanvas()
        canvas_card = QFrame(objectName="DemCanvasCard")
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

        self.open_button.clicked.connect(self.open_dem)
        self.save_button.clicked.connect(self.save_surface)
        self.fit_button.clicked.connect(self.canvas.fit)
        self.folder_button.clicked.connect(self._open_folder)
        self.product_box.currentIndexChanged.connect(lambda _i: self.render())
        for control in (self.z_factor, self.azimuth, self.altitude, self.interval):
            control.valueChanged.connect(lambda _v: self.render())
        self.canvas.hovered.connect(self._on_hovered)
        self.canvas.left_image.connect(self._on_left)
        self._set_ready(False)

    # ------------------------------------------------------------- panel
    def _build_panel(self) -> None:
        self.product_box = QComboBox()
        self.product_box.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, label in PRODUCTS:
            self.product_box.addItem(label, key)

        self.z_factor = self._spin(0.1, 10.0, 1.0, 0.1, " ×")
        self.azimuth = self._spin(0.0, 360.0, 315.0, 5.0, "°")
        self.altitude = self._spin(0.0, 90.0, 45.0, 5.0, "°")
        self.interval = self._spin(0.0, 100000.0, 0.0, 10.0, " m")  # 0 = a sensible automatic interval
        self.interval.setSpecialValueText("auto")

        self._controls = QGridLayout()
        self._controls.setHorizontalSpacing(12)
        self._controls.setVerticalSpacing(6)
        self._control_rows = {
            "z_factor": (QLabel("Z-factor", objectName="Muted"), self.z_factor),
            "azimuth": (QLabel("Sun azimuth", objectName="Muted"), self.azimuth),
            "altitude": (QLabel("Sun altitude", objectName="Muted"), self.altitude),
            "interval": (QLabel("Contour interval", objectName="Muted"), self.interval),
        }
        for row, key in enumerate(("z_factor", "azimuth", "altitude", "interval")):
            label, widget = self._control_rows[key]
            self._controls.addWidget(label, row, 0)
            self._controls.addWidget(widget, row, 1)
        self._controls.setColumnStretch(1, 1)

        self.legend = RasterLegend()
        self.pointer_label = QLabel("Point at the map to read the elevation.", objectName="Muted")
        self.pointer_label.setWordWrap(True)

        self.detail_labels: dict[str, QLabel] = {}
        details = QGridLayout()
        details.setHorizontalSpacing(12)
        details.setVerticalSpacing(4)
        for row, (key, name) in enumerate((("size", "Size"), ("elevation", "Elevation"), ("cell", "Cell size"),
                                           ("crs", "Coordinates"), ("extent", "Extent"), ("file_size", "File size"))):
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
        column.addWidget(_section("Surface"))
        column.addWidget(self.product_box)
        column.addLayout(self._controls)
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
        self._panel = QFrame(objectName="DemPanel")
        self._panel.setFixedWidth(PANEL_WIDTH)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(scroll)

    def _spin(self, low: float, high: float, value: float, step: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setDecimals(1)
        return spin

    # ------------------------------------------------------------- opening & rendering
    def open_dem(self) -> None:
        start = str(Path(self.info.path).parent) if self.info else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open DEM", start, "GeoTIFF (*.tif *.tiff);;All files (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        self.info, self.product = None, None
        self.canvas.clear()
        self.subtitle.setText(Path(path).name)
        self._set_ready(False)
        self.banner.show_info("Reading the DEM…")
        run_task(self, self._facade.describe_dem, path, on_success=self._on_described, on_error=self._on_error)

    def _on_described(self, info: TerrainInfoDTO) -> None:
        self.info = info
        self._fill_details(info)
        self.subtitle.setText(f"{info.name}  ·  {info.width:,} × {info.height:,} px  ·  "
                              f"{info.min_elevation:,.0f}–{info.max_elevation:,.0f} m")
        self._set_ready(True)
        self.render()

    def render(self) -> None:
        if self.info is None:
            return
        product = self.product_box.currentData()
        self._show_controls(product)
        self.banner.show_info(f"Computing {self.product_box.currentText().lower()}…")
        run_task(self, self._facade.render_terrain, self.info, product, self._params(),
                 on_success=self._on_rendered, on_error=self._on_error)

    def _on_rendered(self, product: TerrainProductDTO) -> None:
        same = self.product is not None and (self.product.width, self.product.height) == (product.width, product.height)
        self.product = product
        self.canvas.set_image(rgba_to_image(product.rgba), keep_view=same)
        self.legend.set_legend(product.legend)
        self.banner.show_info(" ".join(product.notes)) if product.notes else self.banner.clear()
        self.save_button.setEnabled(product.values is not None)
        self.pdf_button.setEnabled(True)
        if self._pointer is not None:
            self._read_value()

    # ------------------------------------------------------------- PDF
    def layout_spec(self):
        """The shown surface for the PDF designer, with a boundary layer the user may add there
        (projected onto the DEM's coordinate system)."""
        from frontend.views.map_layout_dialog import MapLayoutSpec

        product, info = self.product, self.info
        legend = product.legend
        if legend.kind == "scale":
            spec_legend = ("scale", tuple(legend.colours), legend.low, legend.high)
        elif legend.kind == "classes":
            spec_legend = ("classes", list(zip(legend.labels, legend.colours)))
        else:
            spec_legend = ()

        def load_boundary(path: str):
            return self._facade.vector_rings_in_crs(self._facade.load_shapefile(path), info.crs)

        note = f"{info.name} · {info.crs} · {product.label}" + (f" · {' '.join(product.notes)}" if product.notes
                                                                 else "")
        return MapLayoutSpec(title=f"{product.label} — {info.name}", image=rgba_to_image(product.rgba),
                             extent=info.bounds, geographic=info.is_geographic, legend_title=legend.title,
                             legend=spec_legend, note=note, load_boundary=load_boundary)

    def export_pdf(self) -> None:
        if self.product is None or self.info is None:
            return
        from frontend.views.map_layout_dialog import MapLayoutDialog

        dialog = MapLayoutDialog(self.layout_spec(), self)
        dialog.exec()
        if dialog.exported:
            self.banner.show_info(f"Map exported to {dialog.exported}")

    def _params(self) -> dict:
        return {"z_factor": self.z_factor.value(), "azimuth": self.azimuth.value(),
                "altitude": self.altitude.value(), "interval": self.interval.value()}

    def _show_controls(self, product: str) -> None:
        visible = {
            "elevation": ("z_factor",), "hillshade": ("z_factor", "azimuth", "altitude"),
            "slope": ("z_factor",), "aspect": (), "contours": ("interval",),
        }.get(product, ())
        for key, (label, widget) in self._control_rows.items():
            label.setVisible(key in visible)
            widget.setVisible(key in visible)

    def save_surface(self) -> None:
        if self.info is None or self.product is None or self.product.values is None:
            return
        suggested = f"{self.info.name}_{self.product.key}.tif"
        path, _ = QFileDialog.getSaveFileName(self, "Save surface", suggested, "GeoTIFF (*.tif)")
        if not path:
            return
        run_task(self, self._facade.save_terrain_product, self.info, self.product.key, path, self._params(),
                 on_success=self._on_saved, on_error=self._on_error)

    def _on_saved(self, path: str) -> None:
        self.banner.show_info(f"Saved to {path}")

    def _on_error(self, exc: Exception) -> None:
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "The DEM could not be processed.")

    # ------------------------------------------------------------- details & pointer
    def _fill_details(self, info: TerrainInfoDTO) -> None:
        west, south, east, north = info.bounds
        unit = "°" if info.is_geographic else "m"
        texts = {
            "size": f"{info.width:,} × {info.height:,} px",
            "elevation": f"{info.min_elevation:,.0f} to {info.max_elevation:,.0f} m  (mean {info.mean_elevation:,.0f})",
            "cell": f"{info.cell_size[0]:g} × {info.cell_size[1]:g} {unit}",
            "crs": info.crs,
            "extent": f"{south:.4f} to {north:.4f}\n{west:.4f} to {east:.4f}",
            "file_size": format_size(info.size_bytes),
        }
        for key, text in texts.items():
            self.detail_labels[key].setText(text)

    def _on_hovered(self, x: float, y: float) -> None:
        self._pointer = (x, y)
        self._hover_timer.start()

    def _on_left(self) -> None:
        self._pointer = None
        self._hover_timer.stop()
        self.pointer_label.setText("Point at the map to read the elevation.")

    def _read_value(self) -> None:
        if self._pointer is None or self.product is None or self.product.values is None:
            return
        x, y = self._pointer
        values = self.product.values
        col = min(values.shape[1] - 1, max(0, int(x)))
        row = min(values.shape[0] - 1, max(0, int(y)))
        value = values[row, col]
        formatted = format_value(value)  # "no data" for a NaN (no-data) pixel; NumPy floats included
        text = formatted if formatted == "no data" else f"{formatted}{self.product.unit}"
        self.pointer_label.setText(f"{self.product.label}: {text}")

    def _open_folder(self) -> None:
        if self.info is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.info.path).parent)))

    def _set_ready(self, ready: bool) -> None:
        for widget in (self.product_box, self.fit_button, self.folder_button):
            widget.setEnabled(ready)
        self.save_button.setEnabled(ready and self.product is not None and self.product.values is not None)
