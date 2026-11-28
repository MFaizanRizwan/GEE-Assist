"""Prediction (ML) page: learn from past and present GeoTIFFs and predict.

1. Task: forecast future values, predict future land cover, classify the present image, or
   detect anomalies.
2. Data: the dated GeoTIFFs (from the project or the computer); the latest is "the present".
   The band to predict, the date to predict for, and (classify) where the labels come from.
3. Algorithms: pick any of them, by family; the recommended ones are pre-selected.
4. Techniques: ensemble, hyperparameter search, PCA, cross-validation, feature importance,
   how many past dates and training pixels, and the working resolution.

Run trains and scores every chosen algorithm on data it did not see, ranks them in the
leaderboard and maps the best one; click another row to see its map. The map shows the
prediction, its confidence or uncertainty, and the change from the present, with the value
under the pointer and a legend. "Save GeoTIFF…" writes the shown model's layers.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QBuffer, QDate, QIODevice, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.prediction_dto import (
    ANOMALY,
    CHANGE,
    CLASSIFY,
    FORECAST,
    TASK_LABELS,
    AlgorithmDTO,
    PredictionInputDTO,
    PredictionOptionsDTO,
    PredictionProgress,
    PredictionRequestDTO,
    PredictionResultDTO,
    RasterBandsDTO,
)
from backend.exceptions import GeeAssistError
from frontend import theme, theming
from frontend.views.full_map_window import MapExtras
from frontend.widgets.flow_layout import FlowLayout
from frontend.widgets.form_parts import StatusBanner
from frontend.widgets.layer_meaning import meaning
from frontend.widgets.map_area import MapArea
from frontend.widgets.raster_canvas import rgba_to_image
from frontend.widgets.raster_legend import format_value
from frontend.widgets.symbology import colorize, ramp_stops
from frontend.workers.task_worker import run_task

PANEL_WIDTH = 380
PROGRESS_POLL_MS = 120
MAP_IMAGE_SIZE = 1024

TASK_HELP = {
    FORECAST: "Predict a layer's values (e.g. NDVI, temperature, a water index) on a future date, pixel by "
              "pixel, from its past values. Needs a past and a present image; three or more dates score better.",
    CHANGE: "Predict each pixel's land-cover class on a future date, and where it will change, from past and "
            "present class maps (e.g. Dynamic World 'label' or an LULC result).",
    CLASSIFY: "Map the land cover of the present image from labelled examples: a class GeoTIFF (e.g. a past "
              "classified map) or a shapefile of labelled points or areas.",
    ANOMALY: "Find pixels whose present value is unusual compared with their own past (drought, fire, flooding, "
             "clearing). Needs two past dates and the present.",
}

# layer keys of the result map
PREDICTION, CONFIDENCE, UNCERTAINTY, DIFFERENCE, PRESENT = "prediction", "confidence", "uncertainty", "difference", \
    "present"


def _stylesheet():
    return f"""
#PredictionPage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20.6pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#PredictPanel, QFrame#PredictCard {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px;
}}
QFrame#PredictPanel QLabel, QFrame#PredictCard QLabel {{ background: transparent; }}
QLabel#SectionTitle {{ color: {theme.MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#StepTitle {{ color: {theme.INK}; font-weight: 700; font-size: 10.5pt; }}
QLabel#Help {{ color: {theme.MUTED}; font-size: 8.5pt; }}
QPushButton#TaskTile {{
    text-align: left; padding: 8px 10px; border-radius: 8px; border: 1px solid {theme.BORDER_STRONG};
    background: {theme.FIELD_BG}; color: {theme.INK}; font-weight: 600;
}}
QPushButton#TaskTile:hover {{ border-color: {theme.BORDER_HOVER}; }}
QPushButton#TaskTile:checked {{ border: 1.5px solid {theme.LEAF}; background: {theme.ACCENT_SOFT or theme.MINT}; }}
QComboBox, QDoubleSpinBox, QSpinBox, QDateEdit {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px;
    padding: 5px 8px; color: {theme.INK};
}}
QTableWidget, QTreeWidget {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; color: {theme.TEXT};
    gridline-color: {theme.TABLE_LINE};
}}
QTableWidget::item:selected, QTreeWidget::item:selected {{ background: {theme.MINT}; color: {theme.INK}; }}
QHeaderView::section {{
    background: {theme.WHITE}; color: {theme.MUTED}; border: none; border-bottom: 1px solid {theme.BORDER};
    padding: 5px 6px; font-weight: 600; font-size: 8.5pt;
}}
QProgressBar {{ border: 1px solid {theme.BORDER_STRONG}; border-radius: 6px; height: 10px; background: {theme.FIELD_BG};
               text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {theme.LEAF}; border-radius: 5px; }}
"""


def _section(title: str) -> QLabel:
    return QLabel(title.upper(), objectName="SectionTitle")


def _step(number: int, title: str) -> QLabel:
    return QLabel(f"{number}  {title}", objectName="StepTitle")


def _help(text: str) -> QLabel:
    label = QLabel(text, objectName="Help")
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class ImportanceBars(QWidget):
    """Horizontal bars: how much the model's score drops when each feature is shuffled."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[tuple[str, float]] = []
        self.setMinimumHeight(40)

    def set_rows(self, rows: list[tuple[str, float]]) -> None:
        self._rows = rows[:10]
        self.setMinimumHeight(max(40, 22 * len(self._rows) + 6))
        self.updateGeometry()
        self.update()

    def rows(self) -> list[tuple[str, float]]:
        return list(self._rows)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._rows:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             "Feature importance appears after a run.")
            return
        top = max(max(v for _n, v in self._rows), 1e-12)
        label_w = int(self.width() * 0.48)
        for i, (name, value) in enumerate(self._rows):
            y = 4 + i * 22
            painter.setPen(QColor(theme.TEXT))
            metrics = painter.fontMetrics()
            painter.drawText(0, y, label_w - 6, 18, Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(name, Qt.TextElideMode.ElideRight, label_w - 6))
            width = max(0.0, value / top) * (self.width() - label_w - 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.LEAF))
            painter.drawRoundedRect(label_w, y + 4, int(width), 10, 3, 3)
        painter.end()


class PredictionView(QWidget):
    show_on_map_requested = pyqtSignal(bytes, object, str, object)   # PNG, bounds, title, MapExtras
    prediction_ready = pyqtSignal(object)                            # PredictionResultDTO (tests / hooks)

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PredictionPage")
        theming.styled(self, _stylesheet)
        self._facade = facade
        self.task = FORECAST
        self.inputs: list[PredictionInputDTO] = []
        self._described: dict[str, RasterBandsDTO] = {}
        self.algorithms: list[AlgorithmDTO] = []
        self.result: PredictionResultDTO | None = None
        self._shown_key = ""          # the model whose map is shown
        self._layer = PREDICTION
        self._layer_values: np.ndarray | None = None
        self._progress: PredictionProgress | None = None
        self.running = False

        self.title = QLabel("Prediction (ML)", objectName="PageTitle")
        self.subtitle = QLabel("Learn from past and present imagery and predict: future values, future land cover, "
                               "a classified map, or anomalies.", objectName="PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.banner = StatusBanner()

        self._build_panel()
        results = self._build_results()

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._panel)
        body.addWidget(results, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.banner)
        layout.addLayout(body, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(PROGRESS_POLL_MS)
        self._timer.timeout.connect(self._tick)
        self.choose_task(FORECAST)
        self._show_result_actions(False)

    # ================================================================ panel
    def _build_panel(self) -> None:
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(8)

        # ---- 1 task
        column.addWidget(_step(1, "Task"))
        self.task_group = QButtonGroup(self)
        self.task_tiles: dict[str, QPushButton] = {}
        tiles = QGridLayout()
        tiles.setSpacing(6)
        for i, task in enumerate((FORECAST, CHANGE, CLASSIFY, ANOMALY)):
            tile = QPushButton(TASK_LABELS[task], objectName="TaskTile")
            tile.setCheckable(True)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            tile.setToolTip(TASK_HELP[task])
            tile.clicked.connect(lambda _=False, t=task: self.choose_task(t))
            self.task_group.addButton(tile)
            tiles.addWidget(tile, i, 0)
            self.task_tiles[task] = tile
        column.addLayout(tiles)
        self.task_help = _help("")
        column.addWidget(self.task_help)
        column.addSpacing(6)

        # ---- 2 data
        column.addWidget(_step(2, "Data"))
        self.input_table = QTableWidget(0, 3)
        self.input_table.setHorizontalHeaderLabels(("Date", "File", "Role"))
        self.input_table.verticalHeader().hide()
        self.input_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.input_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.input_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.input_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.input_table.setMinimumHeight(120)
        self.input_table.setMaximumHeight(190)
        self.input_table.setToolTip("Double-click a date to correct it. The latest date is the present.")
        self.input_table.itemChanged.connect(self._on_date_edited)
        column.addWidget(self.input_table)
        data_buttons = FlowLayout(spacing=6)
        self.project_button = QPushButton("Add from project…", objectName="SecondaryButton")
        self.files_button = QPushButton("Add files…", objectName="SecondaryButton")
        self.remove_button = QPushButton("Remove", objectName="SecondaryButton")
        for button in (self.project_button, self.files_button, self.remove_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            data_buttons.addWidget(button)
        column.addLayout(data_buttons)
        self.data_note = _help("")
        column.addWidget(self.data_note)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self.band_box = QComboBox()
        self.band_label = QLabel("Band", objectName="Muted")
        self.target_date = QDateEdit()
        self.target_date.setCalendarPopup(True)
        self.target_date.setDisplayFormat("yyyy-MM-dd")
        self.target_date.setDate(QDate.currentDate().addYears(1))   # until the files' dates suggest one
        self.target_label = QLabel("Predict for", objectName="Muted")
        self.labels_button = QPushButton("Choose labels…", objectName="SecondaryButton")
        self.labels_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.labels_label = QLabel("Labels", objectName="Muted")
        self.label_choice = QComboBox()
        self.label_choice_label = QLabel("Label band", objectName="Muted")
        self.labels_note = _help("")
        for row, (name, widget) in enumerate(((self.band_label, self.band_box), (self.target_label, self.target_date),
                                              (self.labels_label, self.labels_button),
                                              (self.label_choice_label, self.label_choice))):
            form.addWidget(name, row, 0)
            form.addWidget(widget, row, 1)
        form.setColumnStretch(1, 1)
        column.addLayout(form)
        column.addWidget(self.labels_note)
        self._label_path = ""
        column.addSpacing(6)

        # ---- 3 algorithms
        column.addWidget(_step(3, "Algorithms"))
        self.algorithm_tree = QTreeWidget()
        self.algorithm_tree.setHeaderHidden(True)
        self.algorithm_tree.setMinimumHeight(230)
        self.algorithm_tree.itemChanged.connect(lambda *_: self._update_run_button())
        column.addWidget(self.algorithm_tree)
        picks = FlowLayout(spacing=6)
        self.recommended_button = QPushButton("Recommended", objectName="SecondaryButton")
        self.all_button = QPushButton("All", objectName="SecondaryButton")
        self.none_button = QPushButton("None", objectName="SecondaryButton")
        for button, mode in ((self.recommended_button, "recommended"), (self.all_button, "all"),
                             (self.none_button, "none")):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, m=mode: self.select_algorithms(m))
            picks.addWidget(button)
        column.addLayout(picks)
        column.addSpacing(6)

        # ---- 4 techniques
        column.addWidget(_step(4, "Techniques"))
        self.ensemble_box = QCheckBox("Ensemble of the best three")
        self.ensemble_box.setChecked(True)
        self.tune_box = QCheckBox("Tune hyperparameters (slower)")
        self.tune_box.setToolTip("A randomised search over each algorithm's main settings, scored by 3-fold "
                                 "cross-validation; the best settings are then used")
        self.importance_box = QCheckBox("Feature importance (permutation)")
        self.importance_box.setChecked(True)
        self.pca_box = QCheckBox("Reduce features with PCA (95% variance)")
        self.cv_box = QCheckBox("5-fold cross-validation")
        for box in (self.ensemble_box, self.tune_box, self.importance_box, self.pca_box, self.cv_box):
            column.addWidget(box)
        knobs = QGridLayout()
        knobs.setHorizontalSpacing(10)
        knobs.setVerticalSpacing(6)
        self.lags = self._spin(1, 12, 3, "")
        self.lags.setToolTip("How many of the latest past dates each pixel's prediction looks at")
        self.sample_size = self._spin(500, 500_000, 20_000, "")
        self.sample_size.setSingleStep(5000)
        self.sample_size.setToolTip("Pixels drawn at random to train on (more: slower, often better)")
        self.working_size = self._spin(64, 2048, 512, " px")
        self.working_size.setSingleStep(128)
        self.working_size.setToolTip("Longest side of the grid the prediction is computed on")
        self.neighbourhood = self._spin(0, 5, 1, "")
        self.neighbourhood.setToolTip("Radius (cells) of the window whose class shares describe a pixel's surroundings")
        self.contamination = QDoubleSpinBox()
        self.contamination.setRange(0.1, 40.0)
        self.contamination.setValue(5.0)
        self.contamination.setSuffix(" %")
        self.contamination.setToolTip("The share of pixels flagged as anomalies")
        self._knob_rows = {}
        for row, (key, name, widget) in enumerate((
                ("lags", "Past dates used", self.lags), ("sample", "Training pixels", self.sample_size),
                ("size", "Working size", self.working_size), ("neighbourhood", "Neighbourhood", self.neighbourhood),
                ("contamination", "Expected anomalies", self.contamination))):
            label = QLabel(name, objectName="Muted")
            knobs.addWidget(label, row, 0)
            knobs.addWidget(widget, row, 1)
            self._knob_rows[key] = (label, widget)
        knobs.setColumnStretch(1, 1)
        column.addLayout(knobs)
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        # ---- run
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.hide()
        self.progress_text = _help("")
        self.progress_text.hide()
        self.run_button = QPushButton("Run prediction", objectName="PrimaryButton")
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        run_box = QVBoxLayout()
        run_box.setContentsMargins(18, 8, 18, 14)
        run_box.setSpacing(6)
        run_box.addWidget(self.progress_text)
        run_box.addWidget(self.progress_bar)
        run_box.addWidget(self.run_button)

        self._panel = QFrame(objectName="PredictPanel")
        self._panel.setFixedWidth(PANEL_WIDTH)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        panel_layout.addWidget(scroll, 1)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        theming.styled(divider, lambda: f"color: {theme.BORDER};")
        panel_layout.addWidget(divider)
        panel_layout.addLayout(run_box)

        self.project_button.clicked.connect(self._project_menu)
        self.files_button.clicked.connect(self.add_files)
        self.remove_button.clicked.connect(self.remove_selected)
        self.labels_button.clicked.connect(self.choose_labels)
        self.run_button.clicked.connect(self._run_or_cancel)
        self.band_box.currentIndexChanged.connect(lambda *_: self._update_run_button())

    def _spin(self, low: int, high: int, value: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    # ================================================================ results column
    def _build_results(self) -> QWidget:
        self.result_title = QLabel("No prediction yet", objectName="StepTitle")
        self.result_title.setWordWrap(True)
        self.layer_box = QComboBox()
        self.layer_box.setMinimumWidth(190)
        self.layer_box.currentIndexChanged.connect(self._on_layer_chosen)
        self.save_button = QPushButton("Save GeoTIFF…", objectName="PrimaryButton")
        self.map_button = QPushButton("Show on map", objectName="SecondaryButton")
        for button in (self.save_button, self.map_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self.save)
        self.map_button.clicked.connect(self.show_on_map)
        top = QHBoxLayout()
        top.addWidget(self.result_title, 1)
        top.addWidget(QLabel("Layer", objectName="Muted"))
        top.addWidget(self.layer_box)
        top.addWidget(self.save_button)
        top.addWidget(self.map_button)

        self.map_area = MapArea(dark=False)
        self.map_area.canvas.setMinimumHeight(260)
        self.map_area.set_value_probe(self._value_at)

        map_card = QFrame(objectName="PredictCard")
        map_layout = QVBoxLayout(map_card)
        map_layout.setContentsMargins(14, 12, 14, 12)
        map_layout.setSpacing(8)
        map_layout.addLayout(top)
        map_layout.addWidget(self.map_area, 1)

        self.leaderboard = QTableWidget(0, 0)
        self.leaderboard.verticalHeader().hide()
        self.leaderboard.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.leaderboard.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.leaderboard.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.leaderboard.itemSelectionChanged.connect(self._on_model_chosen)
        self.validation_note = _help("Train and run to see how every algorithm scores on data it did not see.")
        self.importance = ImportanceBars()

        board_card = QFrame(objectName="PredictCard")
        board = QHBoxLayout(board_card)
        board.setContentsMargins(14, 12, 14, 12)
        board.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(_section("Leaderboard"))
        left.addWidget(self.leaderboard, 1)
        left.addWidget(self.validation_note)
        right = QVBoxLayout()
        self.importance_title = _section("Feature importance")
        self.importance_title.setWordWrap(True)
        right.addWidget(self.importance_title)
        right.addWidget(self.importance)
        right.addStretch(1)
        right_box = QWidget()
        right_box.setLayout(right)
        right_box.setFixedWidth(270)
        board.addLayout(left, 1)
        board.addWidget(right_box)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(map_card)
        splitter.addWidget(board_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        return splitter

    # ================================================================ task
    def choose_task(self, task: str) -> None:
        self.task = task
        self.task_tiles[task].setChecked(True)
        self.task_help.setText(TASK_HELP[task])
        forecasting = task in (FORECAST, CHANGE)
        for widget in (self.target_label, self.target_date):
            widget.setVisible(forecasting)
        for widget in (self.labels_label, self.labels_button, self.label_choice_label, self.label_choice,
                       self.labels_note):
            widget.setVisible(task == CLASSIFY)
        for widget in (self.band_label, self.band_box):
            widget.setVisible(task != CLASSIFY)
        self.band_label.setText("Class band" if task == CHANGE else "Band")
        self._show_knob("lags", forecasting)
        self._show_knob("neighbourhood", task == CHANGE)
        self._show_knob("contamination", task == ANOMALY)
        self.pca_box.setVisible(task == CLASSIFY)
        self.cv_box.setVisible(task == CLASSIFY)
        self.tune_box.setVisible(task != ANOMALY)
        self.importance_box.setVisible(task != ANOMALY)
        self.ensemble_box.setText("Consensus of all detectors" if task == ANOMALY else "Ensemble of the best three")
        try:
            self.algorithms = self._facade.prediction_algorithms(task)
        except GeeAssistError as exc:
            self.algorithms = []
            self.banner.show_error(str(exc))
        self._fill_algorithms()
        self._refresh_inputs()

    def _show_knob(self, key: str, visible: bool) -> None:
        for widget in self._knob_rows[key]:
            widget.setVisible(visible)

    def _fill_algorithms(self) -> None:
        tree = self.algorithm_tree
        tree.blockSignals(True)
        tree.clear()
        families: dict[str, QTreeWidgetItem] = {}
        for algorithm in self.algorithms:
            parent = families.get(algorithm.family)
            if parent is None:
                parent = QTreeWidgetItem(tree, [algorithm.family])
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                parent.setExpanded(True)
                families[algorithm.family] = parent
            item = QTreeWidgetItem(parent, [algorithm.label])
            item.setData(0, Qt.ItemDataRole.UserRole, algorithm.key)
            item.setToolTip(0, algorithm.description + (f"\n{algorithm.missing}" if algorithm.missing else "")
                            + f"\nLibrary: {algorithm.library}")
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            if not algorithm.available:
                flags &= ~Qt.ItemFlag.ItemIsEnabled
            item.setFlags(flags)
            item.setCheckState(0, Qt.CheckState.Checked if (algorithm.recommended and algorithm.available)
                               else Qt.CheckState.Unchecked)
        tree.blockSignals(False)
        self._update_run_button()

    def select_algorithms(self, mode: str) -> None:
        tree = self.algorithm_tree
        tree.blockSignals(True)
        recommended = {a.key for a in self.algorithms if a.recommended}
        for item in self._algorithm_items():
            key = item.data(0, Qt.ItemDataRole.UserRole)
            on = mode == "all" or (mode == "recommended" and key in recommended)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        tree.blockSignals(False)
        tree.viewport().update()
        self._update_run_button()

    def _algorithm_items(self) -> list[QTreeWidgetItem]:
        items = []
        for i in range(self.algorithm_tree.topLevelItemCount()):
            family = self.algorithm_tree.topLevelItem(i)
            items.extend(family.child(j) for j in range(family.childCount()))
        return items

    def chosen_algorithms(self) -> list[str]:
        return [item.data(0, Qt.ItemDataRole.UserRole) for item in self._algorithm_items()
                if item.checkState(0) == Qt.CheckState.Checked and item.flags() & Qt.ItemFlag.ItemIsEnabled]

    # ================================================================ data
    def _project_menu(self) -> None:
        menu = QMenu(self)
        theming.styled(menu, lambda: theme.MENU_STYLE)
        added = 0
        try:
            datasets = self._facade.list_analysis_datasets()
        except GeeAssistError:
            datasets = []
        try:
            results = self._facade.list_saved_results()
        except GeeAssistError:
            results = []
        if datasets:
            menu.addSection("Downloaded datasets")
            for dataset in datasets:
                when = dataset.end_date or dataset.start_date
                action = menu.addAction(f"{dataset.name or Path(dataset.path).stem}" + (f"  ({when})" if when else ""))
                action.triggered.connect(lambda _=False, p=dataset.path, d=when: self.add_inputs([(p, d)]))
                added += 1
        if results:
            menu.addSection("Saved analysis results")
            for result in results:
                ds = result.dataset
                when = (ds.end_date or ds.start_date) if ds else ""
                label = f"{', '.join(result.processes) or result.category} · {Path(result.output_path).stem}"
                action = menu.addAction(label + (f"  ({when})" if when else ""))
                action.triggered.connect(lambda _=False, p=result.output_path, d=when: self.add_inputs([(p, d)]))
                added += 1
        if not added:
            menu.addAction("Nothing in the open project yet — use Add files…").setEnabled(False)
        menu.exec(self.project_button.mapToGlobal(self.project_button.rect().bottomLeft()))

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add GeoTIFFs", "", "GeoTIFF (*.tif *.tiff);;All files (*)")
        if paths:
            self.add_inputs([(p, "") for p in paths])

    def add_inputs(self, items: list[tuple[str, str]]) -> None:
        """Add GeoTIFFs (path, date or "") to the series; a missing date is guessed from the file."""
        known = {i.path for i in self.inputs}
        problems = []
        for path, when in items:
            if path in known:
                continue
            try:
                info = self._facade.describe_prediction_input(path)
            except GeeAssistError as exc:
                problems.append(str(exc))
                continue
            self._described[path] = info
            day = when or info.date or self._next_free_date()
            self.inputs.append(PredictionInputDTO(path, day, Path(path).stem))
            known.add(path)
        if problems:
            self.banner.show_error(" ".join(problems))
        else:
            self.banner.clear()
        self._refresh_inputs()

    def _next_free_date(self) -> str:
        """A placeholder date for a file whose name gives none (the user corrects it in the table)."""
        used = {i.date for i in self.inputs}
        day = date.today()
        while day.isoformat() in used:
            day -= timedelta(days=1)
        return day.isoformat()

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.input_table.selectedIndexes()}, reverse=True)
        ordered = self._ordered_inputs()
        for row in rows:
            if 0 <= row < len(ordered):
                self.inputs.remove(ordered[row])
        self._refresh_inputs()

    def _ordered_inputs(self) -> list[PredictionInputDTO]:
        def key(item):
            try:
                return date.fromisoformat(item.date)
            except ValueError:
                return date.max
        return sorted(self.inputs, key=key)

    def _refresh_inputs(self) -> None:
        table = self.input_table
        table.blockSignals(True)
        ordered = self._ordered_inputs()
        table.setRowCount(len(ordered))
        for row, item in enumerate(ordered):
            role = "present" if row == len(ordered) - 1 else "past"
            date_item = QTableWidgetItem(item.date)
            date_item.setData(Qt.ItemDataRole.UserRole, item.path)
            file_item = QTableWidgetItem(Path(item.path).name)
            file_item.setToolTip(item.path)
            file_item.setFlags(file_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            role_item = QTableWidgetItem(role)
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, date_item)
            table.setItem(row, 1, file_item)
            table.setItem(row, 2, role_item)
        table.blockSignals(False)
        self._refresh_bands()
        need = {FORECAST: "Add a past and a present image (more dates score better).",
                CHANGE: "Add past and present class maps (land-cover codes).",
                CLASSIFY: "Add the present image to classify, then choose the labels.",
                ANOMALY: "Add at least two past images and the present one."}[self.task]
        self.data_note.setText(need if len(ordered) < (1 if self.task == CLASSIFY else 2)
                               else f"{len(ordered)} image(s): {ordered[0].date} to {ordered[-1].date}.")
        if ordered and self.task in (FORECAST, CHANGE):
            present = date.fromisoformat(ordered[-1].date) if _is_date(ordered[-1].date) else date.today()
            if self.target_date.date().toPyDate() <= present:
                step = self._typical_step(ordered)
                target = present + timedelta(days=step)
                self.target_date.setDate(QDate(target.year, target.month, target.day))
        self._update_run_button()

    @staticmethod
    def _typical_step(ordered) -> int:
        days = [date.fromisoformat(i.date).toordinal() for i in ordered if _is_date(i.date)]
        if len(days) < 2:
            return 365
        return max(1, int(np.median(np.diff(days))))

    def _on_date_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        text = item.text().strip()
        if not _is_date(text):
            self.banner.show_error(f"“{text}” is not a date: use YYYY-MM-DD.")
            self._refresh_inputs()
            return
        self.inputs = [PredictionInputDTO(i.path, text, i.label) if i.path == path else i for i in self.inputs]
        self.banner.clear()
        self._refresh_inputs()

    def _refresh_bands(self) -> None:
        current = self.band_box.currentText()
        infos = [self._described[i.path] for i in self.inputs if i.path in self._described]
        self.band_box.blockSignals(True)
        self.band_box.clear()
        if infos:
            common = [b for b in infos[-1].bands if all(b in other.bands for other in infos)]
            present = self._described[self._ordered_inputs()[-1].path]
            if self.task == CHANGE:   # class bands first
                common = sorted(common, key=lambda b: b not in present.categorical)
            self.band_box.addItems(common)
            if current in common:
                self.band_box.setCurrentText(current)
        self.band_box.blockSignals(False)

    def choose_labels(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Training labels", "",
                                              "Labels (*.tif *.tiff *.shp);;All files (*)")
        if path:
            self.set_labels(path)

    def set_labels(self, path: str) -> None:
        """Use ``path`` (a class GeoTIFF or a shapefile) for the training labels."""
        self._label_path = path
        self.label_choice.clear()
        try:
            if path.lower().endswith(".shp"):
                layer = self._facade.load_shapefile(path)
                self.label_choice_label.setText("Class field")
                self.label_choice.addItems([f.name for f in layer.fields])
                self.labels_note.setText(f"{Path(path).name}: {layer.feature_count:,} labelled "
                                         f"{layer.kind}s. Choose the field holding each one's class.")
            else:
                info = self._facade.describe_prediction_input(path)
                self.label_choice_label.setText("Label band")
                bands = sorted(info.bands, key=lambda b: b not in info.categorical)
                self.label_choice.addItems(bands)
                self.labels_note.setText(f"{Path(path).name}: class codes are read from the chosen band.")
        except GeeAssistError as exc:
            self._label_path = ""
            self.banner.show_error(str(exc))
        self.labels_button.setText(Path(path).name if self._label_path else "Choose labels…")
        self._update_run_button()

    # ================================================================ running
    def request(self) -> PredictionRequestDTO:
        options = PredictionOptionsDTO(
            sample_size=self.sample_size.value(), working_size=self.working_size.value(), lags=self.lags.value(),
            tune=self.tune_box.isChecked() and self.task != ANOMALY,
            ensemble=self.ensemble_box.isChecked(),
            pca=self.pca_box.isChecked() and self.task == CLASSIFY,
            cross_validation=self.cv_box.isChecked() and self.task == CLASSIFY,
            importance=self.importance_box.isChecked() and self.task != ANOMALY,
            contamination=self.contamination.value() / 100.0, neighbourhood=self.neighbourhood.value())
        label_band = self.label_choice.currentText() if not self._label_path.lower().endswith(".shp") else ""
        label_field = self.label_choice.currentText() if self._label_path.lower().endswith(".shp") else ""
        return PredictionRequestDTO(
            task=self.task, inputs=self._ordered_inputs(), band=self.band_box.currentText(),
            target_date=self.target_date.date().toString("yyyy-MM-dd") if self.task in (FORECAST, CHANGE) else "",
            algorithms=self.chosen_algorithms(), options=options, label_path=self._label_path,
            label_band=label_band, label_field=label_field)

    def _ready(self) -> bool:
        minimum = {FORECAST: 2, CHANGE: 2, ANOMALY: 3, CLASSIFY: 1}[self.task]
        if len(self.inputs) < minimum or not self.chosen_algorithms():
            return False
        if self.task == CLASSIFY:
            return bool(self._label_path and self.label_choice.currentText())
        return bool(self.band_box.currentText())

    def _update_run_button(self) -> None:
        if self.running:
            self.run_button.setText("Cancel")
            self.run_button.setEnabled(True)
            return
        count = len(self.chosen_algorithms())
        self.run_button.setText(f"Run prediction ({count} algorithm{'s' if count != 1 else ''})" if count
                                else "Run prediction")
        self.run_button.setEnabled(self._ready())

    def _run_or_cancel(self) -> None:
        if self.running:
            if self._progress is not None:
                self._progress.cancel()
                self.progress_text.setText("Cancelling after the current algorithm…")
            return
        self.run()

    def run(self) -> None:
        if not self._ready():
            return
        request = self.request()
        self._progress = PredictionProgress()
        self.running = True
        self.banner.show_info(f"{TASK_LABELS[self.task]}: training {len(request.algorithms)} algorithm(s)…")
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.progress_text.show()
        self._timer.start()
        self._update_run_button()
        run_task(self, self._facade.run_prediction, request, self._progress, on_success=self._on_result,
                 on_error=self._on_failed)

    def _tick(self) -> None:
        if self._progress is None:
            return
        fraction, message = self._progress.snapshot()
        self.progress_bar.setValue(round(fraction * 1000))
        self.progress_text.setText(message)

    def _finish(self) -> None:
        self.running = False
        self._timer.stop()
        self.progress_bar.hide()
        self.progress_text.hide()
        self._update_run_button()

    def _on_failed(self, exc: Exception) -> None:
        self._finish()
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else f"The prediction failed: {exc}")

    def _on_result(self, result: PredictionResultDTO) -> None:
        self._finish()
        self.result = result
        failed = [s for s in result.scores if s.error]
        best = result.best
        message = f"Best: {best.label} ({result.primary_metric} {best.metrics.get(result.primary_metric, 0):.4g})."
        if failed:
            message += f" {len(failed)} algorithm(s) could not run: see the leaderboard."
        self.banner.show_info(message)
        self._fill_leaderboard()
        self.validation_note.setText(result.validation + "  " + " ".join(result.notes))
        explained = next((s for s in result.scores if s.importance), None)   # the best model with features
        self.importance.set_rows(explained.importance if explained else [])
        self.importance_title.setText(f"FEATURE IMPORTANCE · {explained.label.upper()}" if explained
                                      else "FEATURE IMPORTANCE")
        self._fill_layers()
        self.show_model(best.key)
        self._show_result_actions(True)
        self.prediction_ready.emit(result)

    def _show_result_actions(self, on: bool) -> None:
        for widget in (self.save_button, self.map_button, self.layer_box):
            widget.setEnabled(on)

    # ================================================================ leaderboard
    def _fill_leaderboard(self) -> None:
        result = self.result
        metrics: list[str] = []
        for score in result.scores:
            for name in score.metrics:
                if name not in metrics:
                    metrics.append(name)
        if result.primary_metric in metrics:
            metrics.remove(result.primary_metric)
            metrics.insert(0, result.primary_metric)
        columns = ["#", "Algorithm"] + metrics + ["Time", "Status"]
        board = self.leaderboard
        board.blockSignals(True)
        board.clear()
        board.setColumnCount(len(columns))
        board.setHorizontalHeaderLabels(columns)
        board.setRowCount(len(result.scores))
        for row, score in enumerate(result.scores):
            cells = [str(score.rank) if score.rank else "–", score.label]
            cells += [f"{score.metrics[m]:.4g}" if m in score.metrics else "" for m in metrics]
            cells += [f"{score.seconds:.1f} s" if score.seconds else "", score.error or ("best" if score.rank == 1
                                                                                         else "ok")]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, score.key)
                if score.error:
                    item.setForeground(QColor(theme.ERROR if col == len(cells) - 1 else theme.SUBTLE))
                    item.setToolTip(score.error)
                if col == 2 and score.rank == 1:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                board.setItem(row, col, item)
        header = board.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        board.blockSignals(False)

    def _on_model_chosen(self) -> None:
        rows = self.leaderboard.selectionModel().selectedRows() if self.leaderboard.selectionModel() else []
        if not rows:
            return
        key = self.leaderboard.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        score = self._score(key)
        if score is not None and not score.error:
            self.show_model(key)

    def _score(self, key: str):
        return next((s for s in self.result.scores if s.key == key), None) if self.result else None

    # ================================================================ the map
    def _fill_layers(self) -> None:
        task = self.result.task
        layers = [(PREDICTION, {FORECAST: f"Forecast for {self.result.target_date}",
                                CHANGE: f"Land cover on {self.result.target_date}", CLASSIFY: "Classified map",
                                ANOMALY: "Anomalies"}[task])]
        if task in (CHANGE, CLASSIFY):
            layers.append((CONFIDENCE, "Confidence"))
        if task == ANOMALY:
            layers.append((CONFIDENCE, "Anomaly score"))
        if task == FORECAST and self.result.uncertainty is not None:
            layers.append((UNCERTAINTY, "Uncertainty (model spread)"))
        if task in (FORECAST, CHANGE):
            layers.append((DIFFERENCE, "Change from the present"))
        if self.result.present is not None:
            layers.append((PRESENT, f"Present ({self.result.present_date})"))
        self.layer_box.blockSignals(True)
        self.layer_box.clear()
        for key, label in layers:
            self.layer_box.addItem(label, key)
        self.layer_box.blockSignals(False)
        self._layer = PREDICTION

    def _on_layer_chosen(self, index: int) -> None:
        if index >= 0 and self.result is not None:
            self._layer = self.layer_box.itemData(index)
            self.show_model(self._shown_key)

    def show_model(self, key: str) -> None:
        """Show model ``key``'s map (the chosen layer) and select its leaderboard row."""
        score = self._score(key)
        if score is None or score.error:
            return
        self._shown_key = key
        self.result_title.setText(f"{score.label}  ·  {TASK_LABELS[self.result.task]}")
        rgba, values = self._render(score)
        self._layer_values = values
        self.map_area.set_image(rgba_to_image(rgba), self.result.bounds, self.result.width, keep_view=True)
        self.map_area.set_opacity(1.0)
        board = self.leaderboard
        for row in range(board.rowCount()):
            item = board.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key and \
                    not any(i.row() == row for i in board.selectedIndexes()):
                board.blockSignals(True)
                board.selectRow(row)
                board.blockSignals(False)

    def _render(self, score) -> tuple[np.ndarray, np.ndarray]:
        """The shown layer of ``score`` as RGBA, with its legend set; and its values (for the probe)."""
        result, layer = self.result, self._layer
        categorical = result.task in (CHANGE, CLASSIFY, ANOMALY)
        if layer == PREDICTION and categorical:
            return self._class_layer(score.prediction, "Class" if result.task != ANOMALY else "Anomaly")
        if layer == PREDICTION or layer == PRESENT:
            values = score.prediction if layer == PREDICTION else result.present
            if result.task == CHANGE and layer == PRESENT:
                return self._class_layer(values, "Present class")
            reference = np.concatenate([a[np.isfinite(a)].ravel() for a in
                                        (score.prediction, result.present) if a is not None]) \
                if result.task == FORECAST else values[np.isfinite(values)]
            low, high = _range(reference)
            ramp = "Red–Yellow–Green" if meaning(result.band, "") or "ndvi" in result.band.lower() else "Viridis"
            self.map_area.show_legend_scale(result.band or "Value", ramp_stops(ramp), low, high,
                                            meaning(result.band, ""))
            return colorize(values, ramp, low, high), values
        if layer == CONFIDENCE:
            values = score.confidence
            title = "Anomaly score (0–1)" if result.task == ANOMALY else "Confidence (0–1)"
            ramp = "Magma" if result.task == ANOMALY else "Viridis"
            self.map_area.show_legend_scale(title, ramp_stops(ramp), 0.0, 1.0,
                                            ("Usual", "Most unusual") if result.task == ANOMALY
                                            else ("Unsure", "Confident"))
            return colorize(values, ramp, 0.0, 1.0), values
        if layer == UNCERTAINTY:
            values = result.uncertainty
            low, high = _range(values[np.isfinite(values)], 0.0)
            self.map_area.show_legend_scale("Uncertainty (spread)", ramp_stops("Inferno"), low, high,
                                            ("Models agree", "Models disagree"))
            return colorize(values, "Inferno", low, high), values
        # DIFFERENCE
        if result.task == CHANGE:
            changed = np.where(np.isfinite(score.prediction) & np.isfinite(result.present),
                               np.where(score.prediction != result.present, score.prediction, -1.0), np.nan)
            return self._class_layer(changed, "Changes to", unchanged=True)
        values = score.prediction - result.present
        finite = np.abs(values[np.isfinite(values)])
        span = float(np.percentile(finite, 98)) if finite.size else 1.0
        span = span or 1.0
        self.map_area.show_legend_scale(f"Change in {result.band}", ramp_stops("Blue–Red (diverging)"), -span, span,
                                        ("Lower than now", "Higher than now"))
        return colorize(values, "Blue–Red (diverging)", -span, span), values

    def _class_layer(self, values: np.ndarray, title: str, unchanged: bool = False):
        classes = list(self.result.classes)
        if unchanged:
            classes = [(-1, "No change", "#E3E3E3")] + classes
        rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
        rows = []
        present_codes = set(np.unique(values[np.isfinite(values)]).astype(int).tolist())
        for code, name, colour in classes:
            mask = values == code
            if not mask.any() and code not in present_codes:
                continue
            c = QColor(colour)
            rgba[mask] = (c.red(), c.green(), c.blue(), 255)
            rows.append((name, colour))
        self.map_area.show_legend_classes(title, rows)
        return rgba, values

    def _value_at(self, x: int, y: int):
        """The value of the shown layer under the pointer: (value, what it is)."""
        values = self._layer_values
        if values is None or self.result is None or not (0 <= y < values.shape[0] and 0 <= x < values.shape[1]):
            return None
        value = values[y, x]
        if not np.isfinite(value):
            return ("no data", "")
        label = self.layer_box.currentText()
        names = {code: name for code, name, _c in self.result.classes}
        if self._layer in (PREDICTION, PRESENT) and self.result.task in (CHANGE, CLASSIFY, ANOMALY) or \
                (self._layer == DIFFERENCE and self.result.task == CHANGE):
            code = int(value)
            return ("No change" if code == -1 else names.get(code, f"Class {code}"), label)
        return (format_value(float(value)), label)

    # ================================================================ save / map
    def save(self) -> None:
        if self.result is None:
            return
        score = self._score(self._shown_key) or self.result.best
        suggested = f"prediction_{self.result.task}_{score.key}_{self.result.target_date}.tif"
        path, _ = QFileDialog.getSaveFileName(self, "Save prediction", suggested, "GeoTIFF (*.tif)")
        if path:
            run_task(self, self._facade.save_prediction, self.result, path, score.key,
                     on_success=self._on_saved, on_error=self._on_failed)

    def _on_saved(self, path: str) -> None:
        self.banner.show_info(f"Saved to {path}")
        self._saved_path = path

    def open_saved_folder(self) -> None:
        path = getattr(self, "_saved_path", "")
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def show_on_map(self) -> None:
        if self.result is None:
            return
        image = self.map_area.canvas.image()
        if max(image.width(), image.height()) > MAP_IMAGE_SIZE:
            image = image.scaled(MAP_IMAGE_SIZE, MAP_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.FastTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        values, result = self._layer_values, self.result
        west, south, east, north = result.bounds

        def probe(lon: float, lat: float):
            if not (west <= lon <= east and south <= lat <= north) or values is None:
                return None
            x = min(int((lon - west) / (east - west) * values.shape[1]), values.shape[1] - 1)
            y = min(int((north - lat) / (north - south) * values.shape[0]), values.shape[0] - 1)
            return self._value_at(x, y)

        score = self._score(self._shown_key)
        extras = MapExtras(self.map_area._legend_call, probe)
        self.show_on_map_requested.emit(bytes(buffer.data()), result.bounds,
                                        f"{score.label} · {self.layer_box.currentText()}", extras)


def _is_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


def _range(values: np.ndarray, floor: float | None = None) -> tuple[float, float]:
    values = values[np.isfinite(values)] if values.size else values
    if values.size == 0:
        return 0.0, 1.0
    low, high = float(np.percentile(values, 2)), float(np.percentile(values, 98))
    if floor is not None:
        low = floor
    if high <= low:
        high = low + 1e-6
    return low, high
