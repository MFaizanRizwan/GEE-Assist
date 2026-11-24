"""Data Catalog page: download geodata from providers and open it in the right page.

Pick a provider (Earth Engine vectors, Natural Earth, Geofabrik / OpenStreetMap, or HDX), make
the provider-specific choices, and download. Earth Engine datasets are clipped to an area found
by place name. When a download finishes, "Open" sends it to Vector Maps, the DEM page or IDW,
depending on what it is.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.catalog_dto import CatalogRequestDTO, CatalogResultDTO, CatalogSourceDTO
from backend.dto.place_dto import PlaceDTO
from backend.exceptions import GeeAssistError
from frontend import theme, theming
from frontend.project_paths import downloads_folder
from frontend.widgets.form_parts import StatusBanner
from frontend.workers.task_worker import run_task

def _stylesheet():
    return f"""
#CatalogPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#CatalogCard {{ background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}
QLabel#SectionTitle {{ color: {theme.MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#Attribution {{ color: {theme.MUTED}; font-size: 8.5pt; }}
QComboBox, QLineEdit, QSpinBox {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px;
    padding: 6px 10px; color: {theme.INK};
}}
QProgressBar {{ border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px; height: 16px; text-align: center;
               background: {theme.FIELD_BG}; color: {theme.INK}; }}
QProgressBar::chunk {{ background: {theme.LEAF}; border-radius: 7px; }}
"""


class _ProgressRelay(QObject):
    """Carries download progress from the worker thread to the UI thread (queued signal)."""

    progress = pyqtSignal(int, int)  # received bytes, total bytes (0 = unknown)


def _section(title: str) -> QLabel:
    return QLabel(title.upper(), objectName="SectionTitle")


class DataCatalogView(QWidget):
    open_requested = pyqtSignal(str, str)  # (file path, open_in: "vector" | "dem" | "idw")

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CatalogPage")
        theming.styled(self, _stylesheet)
        self._facade = facade
        self._sources: list[CatalogSourceDTO] = []
        self._loaded = False
        self._aoi_geojson = ""
        self._area_name = ""
        self._places: list[PlaceDTO] = []
        self._dest = downloads_folder(facade)
        self._last_result: CatalogResultDTO | None = None
        self._downloading = False

        self.title = QLabel("Data Catalog", objectName="PageTitle")
        self.subtitle = QLabel("Download boundaries, basemaps and OpenStreetMap data, then open it here.",
                               objectName="PageSubtitle")
        self.banner = StatusBanner()

        # ---- source + provider-specific controls
        self.source_box = QComboBox()
        self.source_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.source_desc = QLabel(objectName="Muted")
        self.source_desc.setWordWrap(True)
        self.attribution = QLabel(objectName="Attribution")
        self.attribution.setWordWrap(True)

        self.dataset_box = QComboBox()
        self.scale_box = QComboBox()
        self.region_box = QComboBox()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("e.g. Pakistan admin boundaries")
        self.max_features = QSpinBox()
        self.max_features.setRange(100, 50000)
        self.max_features.setSingleStep(500)
        self.max_features.setValue(5000)

        # Earth Engine area-of-interest (place search)
        self.place_edit = QLineEdit()
        self.place_edit.setPlaceholderText("Search a place to clip to, e.g. Punjab")
        self.place_button = QPushButton("Find", objectName="SecondaryButton")
        self.place_results = QComboBox()
        self.place_results.hide()
        self.area_label = QLabel("No area chosen.", objectName="Muted")

        self._form = QFormLayout()
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form.setHorizontalSpacing(12)
        self._form.setVerticalSpacing(10)
        self._rows: dict[str, tuple[QWidget, QWidget]] = {}
        self._add_row("dataset", "Dataset", self.dataset_box)
        self._add_row("scale", "Scale", self.scale_box)
        self._add_row("region", "Region", self.region_box)
        self._add_row("query", "Search", self.query_edit)
        area_row = QWidget()
        area_layout = QHBoxLayout(area_row)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(6)
        area_layout.addWidget(self.place_edit, 1)
        area_layout.addWidget(self.place_button)
        self._add_row("area", "Area", area_row)
        self._add_row("area_result", "", self.place_results)
        self._add_row("area_chosen", "", self.area_label)
        self._add_row("max", "Max features", self.max_features)

        # ---- destination + download
        self.dest_label = QLabel(self._dest, objectName="Muted")
        self.dest_label.setWordWrap(True)
        self.dest_button = QPushButton("Change…", objectName="SecondaryButton")
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        dest_row.addWidget(self.dest_label, 1)
        dest_row.addWidget(self.dest_button)

        self.download_button = QPushButton("Download", objectName="PrimaryButton")
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.progress = QProgressBar()
        self.progress.hide()

        # ---- result
        self.result_label = QLabel(objectName="Value")
        self.result_label.setWordWrap(True)
        self.open_button = QPushButton("Open", objectName="PrimaryButton")
        self.open_folder_button = QPushButton("Open folder", objectName="SecondaryButton")
        self.open_button.hide()
        self.open_folder_button.hide()
        result_row = QHBoxLayout()
        result_row.setSpacing(8)
        result_row.addWidget(self.open_button)
        result_row.addWidget(self.open_folder_button)
        result_row.addStretch(1)

        card_body = QVBoxLayout()
        card_body.setContentsMargins(20, 18, 20, 18)
        card_body.setSpacing(10)
        card_body.addWidget(_section("Provider"))
        card_body.addWidget(self.source_box)
        card_body.addWidget(self.source_desc)
        card_body.addSpacing(4)
        card_body.addWidget(_section("Options"))
        card_body.addLayout(self._form)
        card_body.addSpacing(4)
        card_body.addWidget(_section("Save to"))
        card_body.addLayout(dest_row)
        card_body.addSpacing(8)
        card_body.addWidget(self.download_button)
        card_body.addWidget(self.progress)
        card_body.addWidget(self.result_label)
        card_body.addLayout(result_row)
        card_body.addWidget(self.attribution)
        card = QFrame(objectName="CatalogCard")
        card.setLayout(card_body)
        card.setMaximumWidth(680)

        centre = QHBoxLayout()
        centre.addStretch(1)
        centre.addWidget(card, 3)
        centre.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.banner)
        layout.addLayout(centre, 1)
        layout.addStretch(1)

        self._relay = _ProgressRelay()
        self._relay.progress.connect(self._on_progress)
        self.source_box.currentIndexChanged.connect(self._on_source_changed)
        self.place_button.clicked.connect(self.search_place)
        self.place_edit.returnPressed.connect(self.search_place)
        self.place_results.currentIndexChanged.connect(self._on_place_chosen)
        self.dest_button.clicked.connect(self.change_destination)
        self.download_button.clicked.connect(self.download)
        self.open_button.clicked.connect(self._open_result)
        self.open_folder_button.clicked.connect(self._open_folder)

    # ------------------------------------------------------------- loading sources
    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.load_sources()

    def load_sources(self) -> None:
        try:
            self._sources = list(self._facade.list_data_sources())
        except GeeAssistError as exc:
            self.banner.show_error(str(exc))
            return
        self.source_box.blockSignals(True)
        self.source_box.clear()
        for source in self._sources:
            self.source_box.addItem(source.name, source.id)
        self.source_box.blockSignals(False)
        if self._sources:
            self._on_source_changed(0)

    def _add_row(self, key: str, label: str, widget: QWidget) -> None:
        label_widget = QLabel(label, objectName="Muted")
        self._form.addRow(label_widget, widget)
        self._rows[key] = (label_widget, widget)

    def _set_row_visible(self, key: str, visible: bool) -> None:
        for widget in self._rows[key]:
            widget.setVisible(visible)

    def _current_source(self) -> CatalogSourceDTO | None:
        index = self.source_box.currentIndex()
        return self._sources[index] if 0 <= index < len(self._sources) else None

    def _on_source_changed(self, _index: int) -> None:
        source = self._current_source()
        if source is None:
            return
        self.source_desc.setText(source.description)
        self.attribution.setText(f"Source: {source.attribution}" if source.attribution else "")
        self.dataset_box.clear()
        for dataset in source.datasets:
            self.dataset_box.addItem(dataset.label, dataset.id)
        self.scale_box.clear()
        for scale in source.scales:
            self.scale_box.addItem(scale.label, scale.id)
        self.region_box.clear()
        for region in source.regions:
            self.region_box.addItem(region.label, region.id)
        self._set_row_visible("dataset", bool(source.datasets))
        self._set_row_visible("scale", bool(source.scales))
        self._set_row_visible("region", bool(source.regions))
        self._set_row_visible("query", source.supports_search)
        self._set_row_visible("area", source.needs_area)
        self._set_row_visible("area_result", source.needs_area and self.place_results.count() > 0)
        self._set_row_visible("area_chosen", source.needs_area)
        self._set_row_visible("max", source.needs_area)
        self._clear_result()

    # ------------------------------------------------------------- place search (Earth Engine AOI)
    def search_place(self) -> None:
        name = self.place_edit.text().strip()
        if not name:
            return
        self.banner.show_info(f"Searching for '{name}'…")
        run_task(self, self._facade.search_place, name, on_success=self._on_places, on_error=self._on_error)

    def _on_places(self, places: list[PlaceDTO]) -> None:
        self._places = list(places)
        self.place_results.blockSignals(True)
        self.place_results.clear()
        for place in self._places:
            self.place_results.addItem(place.display_name, place.aoi)
        self.place_results.blockSignals(False)
        if self._places:
            self.place_results.show()
            self._set_row_visible("area_result", True)
            self._on_place_chosen(0)
            self.banner.clear()
        else:
            self.banner.show_info("No places found. Try a different name.")

    def _on_place_chosen(self, index: int) -> None:
        if 0 <= index < len(self._places):
            place = self._places[index]
            self._aoi_geojson = place.aoi
            self._area_name = place.name
            self.area_label.setText(f"Area: {place.display_name}")

    # ------------------------------------------------------------- destination
    def change_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save downloads to", self._dest)
        if folder:
            self._dest = folder
            self.dest_label.setText(folder)

    # ------------------------------------------------------------- download
    def download(self) -> None:
        source = self._current_source()
        if source is None or self._downloading:
            return
        if source.needs_area and not self._aoi_geojson:
            self.banner.show_error("Search for a place first — Earth Engine clips the dataset to it.")
            return
        if source.supports_search and not self.query_edit.text().strip():
            self.banner.show_error("Type what to search for.")
            return
        request = CatalogRequestDTO(
            source_id=source.id,
            dataset_id=self.dataset_box.currentData() or "",
            scale_id=self.scale_box.currentData() or "",
            region_id=self.region_box.currentData() or "",
            query=self.query_edit.text().strip(),
            aoi_geojson=self._aoi_geojson if source.needs_area else "",
            area_name=self._area_name if source.needs_area else "",
            max_features=self.max_features.value(),
        )
        self._downloading = True
        self._clear_result()
        self.download_button.setEnabled(False)
        self.progress.setRange(0, 0)  # indeterminate until the first progress callback
        self.progress.show()
        self.banner.show_info(f"Downloading from {source.name}…")
        on_progress = lambda received, total: self._relay.progress.emit(received, total)  # noqa: E731
        run_task(self, self._facade.download_dataset, request, self._dest, on_progress,
                 on_success=self._on_downloaded, on_error=self._on_error)

    def _on_progress(self, received: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(received)
            self.progress.setFormat(f"{received / 1_000_000:.1f} / {total / 1_000_000:.1f} MB  (%p%)")
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat(f"{received / 1_000_000:.1f} MB" if received else "")

    def _on_downloaded(self, result: CatalogResultDTO) -> None:
        self._downloading = False
        self._last_result = result
        self.download_button.setEnabled(True)
        self.progress.hide()
        self.banner.show_info(" · ".join([f"Downloaded: {result.name}"] + result.notes))
        self.result_label.setText(f"{result.name}\n{result.primary_path}")
        self.open_button.setText({"vector": "Open in Vector Maps", "dem": "Open on DEM page",
                                  "idw": "Open in IDW"}.get(result.open_in, "Open"))
        self.open_button.show()
        self.open_folder_button.show()

    def _on_error(self, exc: Exception) -> None:
        self._downloading = False
        self.download_button.setEnabled(True)
        self.progress.hide()
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "The download could not be completed.")

    def _open_result(self) -> None:
        if self._last_result is not None:
            self.open_requested.emit(self._last_result.primary_path, self._last_result.open_in)

    def _open_folder(self) -> None:
        if self._last_result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._last_result.primary_path).parent)))

    def _clear_result(self) -> None:
        self._last_result = None
        self.result_label.setText("")
        self.open_button.hide()
        self.open_folder_button.hide()
