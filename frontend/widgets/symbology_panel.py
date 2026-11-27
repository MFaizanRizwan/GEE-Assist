"""The symbology / statistics side panel for the Analysis result.

For a continuous layer (vegetation, water, LST) it offers a palette grid, invert, a
stretch (Min–Max · 2–98% · ±2σ · Custom) driven by a histogram with draggable handles,
gamma and overlay opacity. For a class layer (land cover) it lists the classes with
their share of the area, a high-contrast palette toggle and per-class show/hide. The
Statistics tab shows the numbers and the distribution. Works in the light (classical)
and dark (modern) Analysis layouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.dto.map_dto import MapLayerDTO
from frontend.widgets import symbology


# --------------------------------------------------------------------- theme
@dataclass
class _Palette:
    bg: str
    card: str
    line: str
    ink: str
    muted: str
    subtle: str
    accent: str
    field: str


def _palette(dark: bool) -> _Palette:
    if dark:
        return _Palette("#0E1613", "#141E1A", "#25332C", "#F3F8F5", "#93A79D", "#6E8278", "#A6E22E", "#172420")
    return _Palette("#FFFFFF", "#F6F8F6", "#E2E7E3", "#1C2B26", "#5A6B63", "#8A9A92", "#2E7D46", "#F1F4F1")


def _section(text: str, p: _Palette) -> QLabel:
    label = QLabel(text.upper())
    label.setStyleSheet(f"color: {p.muted}; font-size: 8pt; font-weight: 700; letter-spacing: 0.7px;")
    return label


# ---------------------------------------------------------- histogram slider
class HistogramSlider(QWidget):
    """A histogram with two draggable handles that set the stretch's low and high."""

    range_changed = pyqtSignal(float, float)

    def __init__(self, dark: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._p = _palette(dark)
        self._counts: list[int] = []
        self._vmin = 0.0
        self._vmax = 1.0
        self._low = 0.0
        self._high = 1.0
        self._ramp = symbology.DEFAULT_RAMP
        self._invert = False
        self._drag: str | None = None
        self.setMinimumHeight(74)
        self.setMouseTracking(True)

    def set_data(self, counts: list[int], vmin: float, vmax: float) -> None:
        self._counts = list(counts)
        self._vmin, self._vmax = vmin, (vmax if vmax > vmin else vmin + 1e-9)
        self.update()

    def set_bounds(self, low: float, high: float) -> None:
        self._low, self._high = low, high
        self.update()

    def set_ramp(self, ramp: str, invert: bool) -> None:
        """Colour the in-range bars by the layer's colour ramp, so the stretch matches the distribution."""
        self._ramp, self._invert = ramp, invert
        self.update()

    def _x(self, value: float) -> float:
        span = self._vmax - self._vmin or 1e-9
        return (value - self._vmin) / span * self.width()

    def _value(self, x: float) -> float:
        return self._vmin + max(0.0, min(1.0, x / max(self.width(), 1))) * (self._vmax - self._vmin)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar_area = self.height() - 16
        if self._counts:
            peak = max(self._counts) or 1
            n = len(self._counts)
            bw = self.width() / n
            table = symbology.ramp_table(self._ramp, self._invert)
            span = (self._high - self._low) or 1e-9
            subtle = QColor(self._p.subtle)
            for i, count in enumerate(self._counts):
                h = (count / peak) * bar_area
                x = i * bw
                value = self._vmin + ((i + 0.5) / n) * (self._vmax - self._vmin)
                if self._low <= value <= self._high:
                    # The same colour the pixel gets: the ramp over the stretch window [low, high].
                    pos = int(round(max(0.0, min(1.0, (value - self._low) / span)) * 255))
                    r, g, b = table[pos]
                    colour = QColor(int(r), int(g), int(b))
                else:
                    colour = subtle
                painter.fillRect(int(x), int(bar_area - h), max(1, int(bw) - 1), int(h) + 1, colour)
        # the selected window + handles
        lo_x, hi_x = self._x(self._low), self._x(self._high)
        painter.setPen(QPen(QColor(self._p.ink), 2))
        painter.drawLine(int(lo_x), 0, int(lo_x), bar_area)
        painter.drawLine(int(hi_x), 0, int(hi_x), bar_area)
        painter.setBrush(QColor(self._p.accent))
        painter.setPen(QPen(QColor(self._p.ink), 1))
        for x in (lo_x, hi_x):
            painter.drawEllipse(int(x) - 5, bar_area - 2, 10, 10)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        x = event.position().x()
        self._drag = "low" if abs(x - self._x(self._low)) <= abs(x - self._x(self._high)) else "high"
        self._move_to(x)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._drag:
            self._move_to(event.position().x())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._drag = None

    def _move_to(self, x: float) -> None:
        value = self._value(x)
        if self._drag == "low":
            self._low = min(value, self._high - (self._vmax - self._vmin) * 0.01)
        else:
            self._high = max(value, self._low + (self._vmax - self._vmin) * 0.01)
        self.update()
        self.range_changed.emit(self._low, self._high)


# ---------------------------------------------------------- distribution chart
class DistributionChart(QWidget):
    """A histogram whose bars are coloured by the layer's colour ramp (red → green for NDVI),
    with the value range and the layer name along the bottom."""

    def __init__(self, dark: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._p = _palette(dark)
        self._counts: list[int] = []
        self._vmin = 0.0
        self._vmax = 1.0
        self._ramp = symbology.DEFAULT_RAMP
        self._invert = False
        self._label = ""
        self.setMinimumHeight(110)

    def set_data(self, counts: list[int], vmin: float, vmax: float, ramp: str,
                 invert: bool, label: str) -> None:
        self._counts = list(counts)
        self._vmin, self._vmax = vmin, (vmax if vmax > vmin else vmin + 1e-9)
        self._ramp, self._invert, self._label = ramp, invert, label
        self.update()

    def set_ramp(self, ramp: str, invert: bool) -> None:
        self._ramp, self._invert = ramp, invert
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if not self._counts:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        label_h = 18
        chart = self.height() - label_h
        peak = max(self._counts) or 1
        n = len(self._counts)
        table = symbology.ramp_table(self._ramp, self._invert)
        bw = self.width() / n
        for i, count in enumerate(self._counts):
            h = (count / peak) * (chart - 2)
            pos = int(((i + 0.5) / n) * 255)
            r, g, b = table[max(0, min(255, pos))]
            painter.fillRect(int(i * bw), int(chart - h), max(1, int(bw) - 1), int(h) + 1, QColor(r, g, b))
        painter.setPen(QColor(self._p.muted))
        from PyQt6.QtGui import QFont
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        y = self.height() - 4
        painter.drawText(0, y, _fmt(self._vmin))
        if self._label:
            painter.setPen(QColor(self._p.subtle))
            painter.drawText(self.rect().adjusted(0, chart, 0, 0),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self._label)
        painter.setPen(QColor(self._p.muted))
        painter.drawText(self.rect().adjusted(0, chart, -2, 0),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, _fmt(self._vmax))
        painter.end()


# ---------------------------------------------------------- palette swatch
class _RampSwatch(QPushButton):
    def __init__(self, name: str, p: _Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.name = name
        self._p = p
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setToolTip(name)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -2, -2)
        gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
        stops = symbology.ramp_stops(self.name)
        last = max(1, len(stops) - 1)
        for i, colour in enumerate(stops):
            gradient.setColorAt(i / last, QColor(colour))
        painter.setBrush(gradient)
        pen = QPen(QColor(self._p.accent) if self.isChecked() else QColor(self._p.line),
                   2 if self.isChecked() else 1)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 7, 7)
        painter.end()


# --------------------------------------------------------------- the panel
@dataclass
class _State:
    ramp: str = symbology.DEFAULT_RAMP
    invert: bool = False
    stretch: str = "p2_98"
    low: float = 0.0
    high: float = 1.0
    gamma: float = 1.0
    opacity: float = 1.0
    high_contrast: bool = False
    hidden: set = field(default_factory=set)   # hidden class labels


class SymbologyPanel(QWidget):
    changed = pyqtSignal()                 # the layer should be recoloured from current_rgba()
    opacity_changed = pyqtSignal(float)
    saved_open_requested = pyqtSignal(str)  # a saved result GeoTIFF (Saved tab) to open in the viewer

    def __init__(self, dark: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._dark = dark
        self._p = _palette(dark)
        self._layer: MapLayerDTO | None = None
        self._run_info: dict = {}
        self.state = _State()
        self._ramp_buttons: dict[str, _RampSwatch] = {}
        self._class_rows: list[tuple[str, str, QPushButton]] = []  # (label, colour, eye button)
        self.setObjectName("SymbologyPanel")
        self._build()
        self._apply_style()

    # ------------------------------------------------------------- build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(14, 12, 14, 8)
        tab_row.setSpacing(4)
        for index, name in enumerate(("Symbology", "Statistics", "Saved")):
            button = QPushButton(name, objectName="SymTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self._pages.setCurrentIndex(i))
            self._tabs.addButton(button, index)
            tab_row.addWidget(button, 1)
        self._tabs.button(0).setChecked(True)
        root.addLayout(tab_row)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_symbology_tab())
        self._pages.addWidget(self._build_statistics_tab())
        self._pages.addWidget(self._build_saved_tab())
        root.addWidget(self._pages, 1)

    def _scroll(self, inner: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _build_symbology_tab(self) -> QWidget:
        # Two faces: continuous controls and class controls, swapped per layer.
        self._sym_stack = QStackedWidget()
        self._sym_stack.addWidget(self._scroll(self._build_continuous()))
        self._sym_stack.addWidget(self._scroll(self._build_classes()))
        return self._sym_stack

    def _build_continuous(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 6, 14, 14)
        box.setSpacing(10)

        ramp_head = QHBoxLayout()
        ramp_head.addWidget(_section("Colour ramp", self._p))
        self.invert_button = QPushButton("Invert", objectName="ToggleChip")
        self.invert_button.setCheckable(True)
        self.invert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.invert_button.toggled.connect(self._on_invert)
        ramp_head.addStretch(1)
        ramp_head.addWidget(self.invert_button)
        box.addLayout(ramp_head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        ramp_group = QButtonGroup(self)
        ramp_group.setExclusive(True)
        for index, name in enumerate(symbology.RAMPS):
            swatch = _RampSwatch(name, self._p)
            swatch.clicked.connect(lambda _=False, n=name: self._on_ramp(n))
            ramp_group.addButton(swatch)
            self._ramp_buttons[name] = swatch
            label = QLabel(name)
            label.setStyleSheet(f"color: {self._p.subtle}; font-size: 8pt;")
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.addWidget(swatch)
            cell.addWidget(label)
            holder = QWidget()
            holder.setLayout(cell)
            grid.addWidget(holder, index // 3, index % 3)  # three across: more ramps, still compact
        box.addLayout(grid)

        box.addWidget(_section("Stretch", self._p))
        self._stretch_buttons: dict[str, QPushButton] = {}
        stretch_row = QGridLayout()  # four across, two rows: eight presets fit the panel
        stretch_row.setHorizontalSpacing(0)
        stretch_row.setVerticalSpacing(4)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (key, label) in enumerate(symbology.STRETCHES):
            button = QPushButton(label, objectName="SegButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._on_stretch(k))
            group.addButton(button)
            self._stretch_buttons[key] = button
            stretch_row.addWidget(button, index // 4, index % 4)
        box.addLayout(stretch_row)

        self.histogram = HistogramSlider(self._dark)
        self.histogram.range_changed.connect(self._on_custom_range)
        box.addWidget(self.histogram)
        self._bounds_label = QLabel()
        self._bounds_label.setStyleSheet(f"color: {self._p.muted}; font-size: 8pt;")
        box.addWidget(self._bounds_label)

        box.addWidget(_section("Classification", self._p))
        self._classif_note = QLabel("Continuous")
        self._classif_note.setStyleSheet(f"color: {self._p.subtle}; font-size: 8pt;")
        box.addWidget(self._classif_note)

        self.gamma_slider, gamma_box, self.gamma_value = self._slider_row("Gamma", 10, 300, 100)
        self.gamma_slider.valueChanged.connect(self._on_gamma)
        box.addLayout(gamma_box)

        self.opacity_slider, opacity_box, self.opacity_value = self._slider_row("Map overlay opacity", 0, 100, 100,
                                                                                percent=True)
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        box.addLayout(opacity_box)

        self.reset_button = QPushButton("↺  Reset symbology", objectName="ResetButton")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.clicked.connect(self.reset_symbology)
        box.addWidget(self.reset_button)
        box.addStretch(1)
        return page

    def _build_classes(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 6, 14, 14)
        box.setSpacing(10)

        box.addWidget(_section("Palette", self._p))
        pal_row = QHBoxLayout()
        pal_row.setSpacing(0)
        self._palette_group = QButtonGroup(self)
        self._palette_group.setExclusive(True)
        self._std_button = QPushButton("Standard", objectName="SegButton")
        self._hc_button = QPushButton("High contrast", objectName="SegButton")
        for button, hc in ((self._std_button, False), (self._hc_button, True)):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, h=hc: self._on_palette(h))
            self._palette_group.addButton(button)
            pal_row.addWidget(button, 1)
        self._std_button.setChecked(True)
        box.addLayout(pal_row)

        box.addWidget(_section("Classes", self._p))
        self._classes_box = QVBoxLayout()
        self._classes_box.setSpacing(6)
        box.addLayout(self._classes_box)

        self.class_opacity_slider, class_opacity_box, self.class_opacity_value = self._slider_row(
            "Map overlay opacity", 0, 100, 100, percent=True)
        self.class_opacity_slider.valueChanged.connect(self._on_opacity)
        box.addLayout(class_opacity_box)

        self.class_reset_button = QPushButton("↺  Reset symbology", objectName="ResetButton")
        self.class_reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.class_reset_button.clicked.connect(self.reset_symbology)
        box.addWidget(self.class_reset_button)
        box.addStretch(1)
        return page

    def _build_statistics_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 10, 14, 14)
        box.setSpacing(12)
        self._stats_grid = QGridLayout()
        self._stats_grid.setHorizontalSpacing(8)
        self._stats_grid.setVerticalSpacing(8)
        box.addLayout(self._stats_grid)
        box.addWidget(_section("Distribution", self._p))
        self._dist = DistributionChart(self._dark)
        box.addWidget(self._dist)
        box.addWidget(_section("Run", self._p))
        self._run_grid = QGridLayout()
        self._run_grid.setHorizontalSpacing(10)
        self._run_grid.setVerticalSpacing(5)
        box.addLayout(self._run_grid)
        box.addStretch(1)
        return self._scroll(page)

    def _build_saved_tab(self) -> QWidget:
        """Every analysis saved in the open project, newest first; click one to open it."""
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 6, 14, 14)
        box.setSpacing(8)
        self._saved_count = _section("Saved in this project", self._p)
        box.addWidget(self._saved_count)
        self._saved_empty = QLabel("No analysis saved in this project yet. Save a result to keep it here.")
        self._saved_empty.setWordWrap(True)
        self._saved_empty.setStyleSheet(f"color: {self._p.muted}; font-size: 9pt;")
        box.addWidget(self._saved_empty)
        self.saved_list = QListWidget(objectName="SavedList")
        self.saved_list.setWordWrap(True)
        self.saved_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.saved_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.saved_list.itemActivated.connect(self._open_saved)
        self.saved_list.itemClicked.connect(self._open_saved)
        box.addWidget(self.saved_list, 1)
        self.set_saved_results([])
        return page

    def set_saved_results(self, rows: list[tuple[str, str, str]]) -> None:
        """``rows``: (GeoTIFF path, title, detail) of every saved analysis, newest first."""
        self.saved_list.clear()
        for path, title, detail in rows:
            item = QListWidgetItem(f"{title}\n{detail}" if detail else title)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(f"{path}\nClick to open it in the viewer")
            self.saved_list.addItem(item)
        count = len(rows)
        self._saved_count.setText(f"SAVED IN THIS PROJECT · {count}" if count else "SAVED IN THIS PROJECT")
        self._saved_empty.setVisible(not rows)
        self.saved_list.setVisible(bool(rows))

    def _open_saved(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.saved_open_requested.emit(path)

    def _slider_row(self, title: str, lo: int, hi: int, value: int, percent: bool = False):
        box = QVBoxLayout()
        box.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_section(title, self._p), 1)
        read = QLabel(f"{value}%" if percent else f"{value / 100:.2f}")
        read.setStyleSheet(f"color: {self._p.accent}; font-weight: 700; font-size: 9pt;")
        read.setAlignment(Qt.AlignmentFlag.AlignRight)
        head.addWidget(read)
        box.addLayout(head)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        slider.setObjectName("SymSlider")
        slider.valueChanged.connect(
            lambda v: read.setText(f"{v}%" if percent else f"{v / 100:.2f}"))
        box.addWidget(slider)
        return slider, box, read

    # ------------------------------------------------------------- data in
    def set_layer(self, layer: MapLayerDTO, run_info: dict | None = None) -> None:
        self._layer = layer
        self._run_info = run_info or {}
        self.state = _State()
        is_scale = layer.kind == "scale" and layer.values is not None
        self._sym_stack.setCurrentIndex(0 if is_scale else 1)
        if is_scale:
            self._init_continuous(layer)
        else:
            self._init_classes(layer)
        self._fill_statistics(layer)

    def _init_continuous(self, layer: MapLayerDTO) -> None:
        stats = layer.stats or {}
        self.state.ramp = self._guess_ramp(layer.style)
        self.state.low, self.state.high = symbology.stretch_bounds("p2_98", stats)
        for name, button in self._ramp_buttons.items():
            button.setChecked(name == self.state.ramp)
        self.invert_button.setChecked(False)
        self._stretch_buttons["p2_98"].setChecked(True)
        counts, edges = (layer.histogram or ([], [0.0, 1.0]))
        vmin = stats.get("min", edges[0] if edges else 0.0)
        vmax = stats.get("max", edges[-1] if edges else 1.0)
        self.histogram.set_data(counts, vmin, vmax)
        self.histogram.set_bounds(self.state.low, self.state.high)
        self.histogram.set_ramp(self.state.ramp, self.state.invert)
        self.gamma_slider.setValue(100)
        self.opacity_slider.setValue(round(self.state.opacity * 100))
        self._update_bounds_label()

    def _init_classes(self, layer: MapLayerDTO) -> None:
        while self._classes_box.count():
            item = self._classes_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._class_rows = []
        self._std_button.setChecked(True)
        self.class_opacity_slider.setValue(100)
        for index, (label, colour, fraction) in enumerate(layer.class_fractions):
            row = self._class_row(index, label, colour, fraction)
            self._classes_box.addWidget(row)

    def _class_row(self, index: int, label: str, colour: str, fraction: float) -> QWidget:
        row = QFrame(objectName="ClassRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)
        swatch = QLabel()
        swatch.setFixedSize(14, 14)
        swatch.setStyleSheet(f"background: {colour}; border-radius: 3px;")
        name = QLabel(label)
        name.setStyleSheet(f"color: {self._p.ink}; font-weight: 600; font-size: 9pt;")
        pct = QLabel(f"{fraction * 100:.1f}%")
        pct.setStyleSheet(f"color: {self._p.muted}; font-size: 9pt;")
        eye = QPushButton("\U0001F441", objectName="EyeButton")
        eye.setCheckable(True)
        eye.setChecked(True)
        eye.setCursor(Qt.CursorShape.PointingHandCursor)
        eye.setFixedWidth(26)
        eye.setToolTip("Show or hide this class")
        eye.toggled.connect(lambda shown, lbl=label: self._on_class_toggle(lbl, shown))
        layout.addWidget(swatch)
        layout.addWidget(name, 1)
        layout.addWidget(pct)
        layout.addWidget(eye)
        self._class_rows.append((label, colour, eye))
        return row

    @staticmethod
    def _guess_ramp(style: str) -> str:
        mapping = {
            "vegetation": "Red–Yellow–Green", "condition": "Red–Yellow–Green",
            "water": "Blues", "turbidity": "Blues", "algae": "Blues",
            "thermal": "Turbo", "change": "Blue–Red (diverging)", "diverging": "Blue–Red (diverging)",
            "burn": "Spectral", "dryness": "Brown–Teal", "soil": "Brown–Teal",
            "grey": "Greyscale",
        }
        return mapping.get(style, symbology.DEFAULT_RAMP)

    # ------------------------------------------------------------- stats
    def _fill_statistics(self, layer: MapLayerDTO) -> None:
        while self._stats_grid.count():
            self._stats_grid.takeAt(0).widget().deleteLater()
        while self._run_grid.count():
            self._run_grid.takeAt(0).widget().deleteLater()
        stats = layer.stats or {}
        if layer.kind == "scale" and stats:
            tiles = (("Mean", stats.get("mean")), ("Std dev", stats.get("std")),
                     ("Min", stats.get("min")), ("Max", stats.get("max")),
                     ("P2", stats.get("p2")), ("P98", stats.get("p98")))
            for i, (name, value) in enumerate(tiles):
                self._stats_grid.addWidget(self._stat_tile(name, _fmt(value)), i // 2, i % 2)
            counts, edges = (layer.histogram or ([], [0.0, 1.0]))
            self._dist.set_data(counts, stats.get("min", 0.0), stats.get("max", 1.0),
                                self.state.ramp, self.state.invert, layer.name)
            self._dist.setVisible(True)
        else:
            self._dist.setVisible(False)
            for i, (label, _colour, fraction) in enumerate(layer.class_fractions):
                self._stats_grid.addWidget(self._stat_tile(label, f"{fraction * 100:.1f}%"), i // 2, i % 2)
        rows = [("Compute", self._run_info.get("device", "")),
                ("Duration", self._run_info.get("duration", "")),
                ("Dataset", self._run_info.get("dataset", "")),
                ("Layer", layer.name)]
        for i, (name, value) in enumerate(rows):
            key = QLabel(name)
            key.setStyleSheet(f"color: {self._p.muted}; font-size: 9pt;")
            val = QLabel(str(value))
            val.setStyleSheet(f"color: {self._p.ink}; font-size: 9pt; font-weight: 600;")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val.setWordWrap(True)
            self._run_grid.addWidget(key, i, 0)
            self._run_grid.addWidget(val, i, 1)
        self._run_grid.setColumnStretch(1, 1)

    def _stat_tile(self, name: str, value: str) -> QFrame:
        tile = QFrame(objectName="StatTile")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        key = QLabel(name.upper())
        key.setStyleSheet(f"color: {self._p.muted}; font-size: 8pt; font-weight: 700; letter-spacing: 0.5px;")
        val = QLabel(value)
        val.setStyleSheet(f"color: {self._p.ink}; font-size: 12.7pt; font-weight: 700;")
        layout.addWidget(key)
        layout.addWidget(val)
        return tile

    # ------------------------------------------------------------- events
    def _on_ramp(self, name: str) -> None:
        self.state.ramp = name
        for other, button in self._ramp_buttons.items():
            button.setChecked(other == name)
        self._dist.set_ramp(self.state.ramp, self.state.invert)
        self.histogram.set_ramp(self.state.ramp, self.state.invert)  # the stretch follows the ramp too
        self.changed.emit()

    def _on_invert(self, on: bool) -> None:
        self.state.invert = on
        self._dist.set_ramp(self.state.ramp, self.state.invert)
        self.histogram.set_ramp(self.state.ramp, self.state.invert)
        self.changed.emit()

    def _on_stretch(self, key: str) -> None:
        self.state.stretch = key
        if key != "custom" and self._layer is not None:
            self.state.low, self.state.high = symbology.stretch_bounds(key, self._layer.stats or {},
                                                                      self._layer.values)
            self.histogram.set_bounds(self.state.low, self.state.high)
            self._update_bounds_label()
        self.changed.emit()

    def _on_custom_range(self, low: float, high: float) -> None:
        self.state.low, self.state.high = low, high
        self.state.stretch = "custom"
        self._stretch_buttons["custom"].setChecked(True)
        self._update_bounds_label()
        self.changed.emit()

    def _on_gamma(self, value: int) -> None:
        self.state.gamma = value / 100
        self.changed.emit()

    def _on_opacity(self, value: int) -> None:
        self.state.opacity = value / 100
        self.opacity_changed.emit(self.state.opacity)

    def _on_palette(self, high_contrast: bool) -> None:
        self.state.high_contrast = high_contrast
        self.changed.emit()

    def _on_class_toggle(self, label: str, shown: bool) -> None:
        if shown:
            self.state.hidden.discard(label)
        else:
            self.state.hidden.add(label)
        self.changed.emit()

    def _update_bounds_label(self) -> None:
        self._bounds_label.setText(f"min {_fmt(self.state.low)}      max {_fmt(self.state.high)}")

    def reset_symbology(self) -> None:
        if self._layer is not None:
            self.set_layer(self._layer, self._run_info)
            self.opacity_changed.emit(1.0)
            self.changed.emit()

    # ------------------------------------------------------------- output
    def current_rgba(self):
        """The recoloured RGBA for the current layer, or None to keep the original."""
        layer = self._layer
        if layer is None:
            return None
        if layer.kind == "scale" and layer.values is not None:
            return symbology.colorize(layer.values, self.state.ramp, self.state.low, self.state.high,
                                      self.state.invert, self.state.gamma)
        # classes: remap / hide against the original colours
        mapping = []
        for index, (label, colour, _eye) in enumerate(self._class_rows):
            if label in self.state.hidden:
                mapping.append((colour, None))
            elif self.state.high_contrast:
                mapping.append((colour, symbology.high_contrast_colour(index)))
            else:
                mapping.append((colour, colour))
        return symbology.recolor_classes(layer.data, mapping)

    def legend_rows(self) -> list[tuple[str, str]]:
        """(label, colour) rows for the map legend, reflecting the current palette / hidden classes."""
        rows = []
        for index, (label, colour, _eye) in enumerate(self._class_rows):
            if label in self.state.hidden:
                continue
            shown = symbology.high_contrast_colour(index) if self.state.high_contrast else colour
            rows.append((label, shown))
        return rows

    def scale_legend(self) -> tuple[tuple[str, ...], float, float]:
        """The legend's colours from low to high, sampled the way colorize() maps values (ramp,
        invert and gamma), with the stretch's low and high."""
        table = symbology.ramp_table(self.state.ramp, self.state.invert)
        gamma = max(self.state.gamma or 1.0, 1e-6)
        steps = 9
        colours = tuple("#%02X%02X%02X" % tuple(table[round((i / (steps - 1)) ** (1.0 / gamma) * 255)])
                        for i in range(steps))
        return colours, self.state.low, self.state.high

    # ------------------------------------------------------------- style
    def _apply_style(self) -> None:
        p = self._p
        self.setStyleSheet(f"""
        #SymbologyPanel {{ background: {p.bg}; }}
        #SymbologyPanel QLabel {{ background: transparent; color: {p.ink}; }}
        QPushButton#SymTab {{
            background: transparent; color: {p.muted}; border: none;
            border-bottom: 2px solid transparent; padding: 7px 4px; font-weight: 700; font-size: 9pt;
        }}
        QPushButton#SymTab:hover {{ color: {p.ink}; }}
        QPushButton#SymTab:checked {{ color: {p.ink}; border-bottom: 2px solid {p.accent}; }}
        QPushButton#SegButton {{
            background: {p.field}; color: {p.muted}; border: 1px solid {p.line};
            padding: 6px 8px; font-weight: 600; font-size: 8pt;
        }}
        QPushButton#SegButton:checked {{ background: {p.card}; color: {p.ink}; border-color: {p.accent}; }}
        QPushButton#ToggleChip {{
            background: {p.field}; color: {p.muted}; border: 1px solid {p.line};
            border-radius: 7px; padding: 3px 12px; font-size: 8pt; font-weight: 600;
        }}
        QPushButton#ToggleChip:checked {{ background: {p.accent}; color: {p.bg}; border-color: {p.accent}; }}
        QFrame#ClassRow, QFrame#StatTile {{
            background: {p.card}; border: 1px solid {p.line}; border-radius: 9px;
        }}
        QFrame#ClassRow QLabel, QFrame#StatTile QLabel {{ background: transparent; }}
        QPushButton#EyeButton {{ background: transparent; border: none; color: {p.muted}; font-size: 10pt; }}
        QPushButton#EyeButton:checked {{ color: {p.accent}; }}
        QPushButton#ResetButton {{
            background: {p.field}; color: {p.ink}; border: 1px solid {p.line};
            border-radius: 9px; padding: 9px 12px; font-weight: 600;
        }}
        QPushButton#ResetButton:hover {{ border-color: {p.accent}; }}
        QListWidget#SavedList {{
            background: transparent; border: none; color: {p.ink}; font-size: 9pt; outline: 0;
        }}
        QListWidget#SavedList::item {{
            background: {p.card}; border: 1px solid {p.line}; border-radius: 9px;
            padding: 8px 10px; margin-bottom: 6px;
        }}
        QListWidget#SavedList::item:hover {{ border-color: {p.accent}; }}
        QListWidget#SavedList::item:selected {{ border-color: {p.accent}; color: {p.ink}; }}
        QScrollArea {{ background: transparent; border: none; }}
        QSlider#SymSlider::groove:horizontal {{ height: 4px; background: {p.line}; border-radius: 2px; }}
        QSlider#SymSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
        QSlider#SymSlider::handle:horizontal {{
            background: {p.accent}; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
        }}
        QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {p.line}; border-radius: 4px; min-height: 28px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)
        # Segmented buttons: round only the outer corners of each strip.
        for buttons in (list(self._stretch_buttons.values()),):
            if buttons:
                buttons[0].setStyleSheet("#SegButton { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }")
                buttons[-1].setStyleSheet("#SegButton { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }")
        self._std_button.setStyleSheet("#SegButton { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }")
        self._hc_button.setStyleSheet("#SegButton { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }")


def _fmt(value) -> str:
    if value is None:
        return "—"
    magnitude = abs(value)
    if magnitude >= 1000 or value == int(value):
        return f"{value:,.0f}"
    if magnitude >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"
