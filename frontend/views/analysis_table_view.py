"""Analysis table: a cheat sheet of every spectral index and method GEE-Assist knows.

Reference only (no analysis runs here): each row gives the index, its formula, the
bands it needs, its value range and what it is used for, grouped by category
(vegetation, water, burn, snow & ice, ...). Category chips and a search box narrow
the table; the panel on the right shows the selected row in full. Opened from
View → Show analysis table.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.analysis_dto import FormulaDTO
from frontend import theme

ALL = "All"
PANEL_WIDTH = 340
COLUMNS = ("Index", "Name", "Formula", "Bands", "Range", "Use cases", "In app")
FORMULA_FONT = "Cambria Math"

# A colour per category, for the chips, the group rows and the badge in the detail panel.
CATEGORY_COLOURS: dict[str, str] = {
    "Vegetation": "#3E9B4F",
    "Moisture & drought": "#B7791F",
    "Water": "#2F7CC4",
    "Burn": "#D0482B",
    "Soil & salinity": "#8C6239",
    "Built-up & urban": "#7A6F86",
    "Snow & ice": "#4FA9C9",
    "Thermal": "#D9534F",
    "Land cover": "#6B8E23",
    "Transformations": "#6C5CE7",
    "SAR (radar)": "#4A5568",
}

ROLE_LABELS = {"coastal": "Coastal", "blue": "Blue", "green": "Green", "red": "Red", "re1": "RE1", "re2": "RE2",
               "re3": "RE3", "nir": "NIR", "nir2": "NIR narrow", "swir1": "SWIR1", "swir2": "SWIR2",
               "thermal": "TIR", "vv": "VV", "vh": "VH", "hh": "HH", "hv": "HV"}

STYLESHEET = f"""
#AnalysisTablePage {{ background: transparent; }}
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; color: {theme.INK}; }}
QLabel#PageSubtitle {{ color: {theme.MUTED}; }}
QFrame#TableCard, QFrame#DetailPanel {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 12px;
}}
QFrame#DetailPanel QLabel {{ background: transparent; }}
QLabel#SectionTitle {{ color: {theme.MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#DetailKey {{ font-family: "{theme.SERIF}"; font-size: 18pt; color: {theme.INK}; }}
QLabel#DetailName {{ color: {theme.INK}; font-weight: 600; }}
QLabel#FormulaBox {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 8px 10px;
    color: {theme.INK}; font-family: "{FORMULA_FONT}", "{theme.SERIF}"; font-size: 11pt;
}}
QLabel#Value {{ color: {theme.TEXT}; }}
QLabel#NoteBox {{
    background: {theme.INFO_BG}; border: 1px solid {theme.INFO_BORDER}; border-radius: 8px; padding: 8px 10px;
    color: {theme.OCEAN_DARK};
}}
QPushButton#CategoryChip {{
    border: 1px solid {theme.BORDER_STRONG}; border-radius: 14px; padding: 4px 12px; font-size: 9pt;
    font-weight: 600; background: {theme.WHITE}; color: {theme.INK};
}}
QPushButton#CategoryChip:hover {{ background: {theme.FOAM}; }}
QPushButton#CategoryChip:checked {{ background: {theme.MINT}; border-color: {theme.LEAF}; }}
QTableWidget {{
    background: {theme.WHITE}; border: none; gridline-color: {theme.TABLE_LINE}; color: {theme.TEXT};
    selection-background-color: {theme.FOAM}; selection-color: {theme.INK};
}}
QHeaderView::section {{
    background: {theme.FIELD_BG}; color: {theme.MUTED}; border: none; border-bottom: 1px solid {theme.BORDER};
    padding: 6px 8px; font-weight: 600; font-size: 9pt;
}}
"""


def _section(title: str) -> QLabel:
    return QLabel(title.upper(), objectName="SectionTitle")


def band_text(formula: FormulaDTO) -> str:
    return ", ".join(ROLE_LABELS.get(role, role) for role in formula.bands) or "—"


def matches(formula: FormulaDTO, query: str) -> bool:
    """Whether the search text appears in the index's key, name, aliases, formula or use cases."""
    if not query:
        return True
    text = " ".join((formula.key, formula.name, formula.formula, formula.category, formula.description,
                     *formula.aliases, *formula.use_cases)).lower()
    return all(word in text for word in query.lower().split())


class FormulaDetail(QFrame):
    """The selected index in full."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DetailPanel")
        self.setFixedWidth(PANEL_WIDTH)
        self.key = QLabel(objectName="DetailKey")
        self.badge = QLabel()
        self.name = QLabel(objectName="DetailName")
        self.formula = QLabel(objectName="FormulaBox")
        self.bands = QLabel(objectName="Value")
        self.range = QLabel(objectName="Value")
        self.description = QLabel(objectName="Value")
        self.interpretation = QLabel(objectName="Value")
        self.use_cases = QLabel(objectName="Value")
        self.reference = QLabel(objectName="Muted")
        self.status = QLabel(objectName="Value")
        self.note = QLabel(objectName="NoteBox")
        for label in (self.name, self.formula, self.bands, self.range, self.description, self.interpretation,
                      self.use_cases, self.reference, self.status, self.note):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.use_cases.setTextFormat(Qt.TextFormat.RichText)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(self.key)
        top.addStretch(1)
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addLayout(top)
        column.addWidget(self.name)
        self._sections: dict[str, list[QWidget]] = {}
        for title, widget in (("Formula", self.formula), ("Bands", self.bands), ("Range", self.range),
                              ("What it shows", self.description), ("Reading the values", self.interpretation),
                              ("Use cases", self.use_cases), ("In GEE-Assist", self.status)):
            header = _section(title)
            column.addSpacing(4)
            column.addWidget(header)
            column.addWidget(widget)
            self._sections[title] = [header, widget]
        column.addWidget(self.note)
        column.addWidget(self.reference)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self.show_formula(None)

    def show_formula(self, formula: FormulaDTO | None) -> None:
        if formula is None:
            self.key.setText("Choose an index")
            self.name.setText("Select a row to see its formula, how to read it and what it is used for.")
            for widgets in self._sections.values():
                for widget in widgets:
                    widget.hide()
            self.badge.hide()
            self.note.hide()
            self.reference.hide()
            return
        for widgets in self._sections.values():
            for widget in widgets:
                widget.show()
        self.key.setText(formula.key)
        aliases = f"  (also: {', '.join(formula.aliases)})" if formula.aliases else ""
        self.name.setText(formula.name + aliases)
        colour = CATEGORY_COLOURS.get(formula.category, theme.OCEAN)
        self.badge.setText(formula.category)
        self.badge.setStyleSheet(f"background: {colour}; color: white; border-radius: 9px; padding: 2px 9px; "
                                 "font-size: 8.5pt; font-weight: 600;")
        self.badge.show()
        self.formula.setText(formula.formula)
        self.bands.setText(band_text(formula) + ("" if formula.periods < 2 else
                                                 f"  ·  needs {formula.periods} dates (before and after)"))
        self.range.setText(formula.value_range or "—")
        self.description.setText(formula.description or "—")
        self.interpretation.setText(formula.interpretation or "—")
        items = "".join(f"<li>{case}</li>" for case in formula.use_cases)
        self.use_cases.setText(f"<ul style='margin: 0; -qt-list-indent: 1;'>{items}</ul>")
        self.status.setText("Computed on the Analysis page." if formula.computable else
                            "Reference only: not computed by GEE-Assist.")
        self.note.setText(formula.note)
        self.note.setVisible(bool(formula.note))
        self.reference.setText(f"Source: {formula.reference}" if formula.reference else "")
        self.reference.setVisible(bool(formula.reference))


class AnalysisTableView(QWidget):
    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AnalysisTablePage")
        self.setStyleSheet(STYLESHEET)
        self._facade = facade
        self.formulas: list[FormulaDTO] = []
        self._loaded = False
        self.category = ALL

        self.title = QLabel("Analysis table", objectName="PageTitle")
        self.subtitle = QLabel("Every spectral index and method: its formula, the bands it needs and what it is "
                               "used for. A cheat sheet; run them on the Analysis page.", objectName="PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: NDVI, flood, salinity, chlorophyll…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(380)
        self.count = QLabel(objectName="Muted")

        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chips: dict[str, QPushButton] = {}

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        header = self.table.horizontalHeader()
        for column, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Interactive,
                                       QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.Interactive,
                                       QHeaderView.ResizeMode.Interactive, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.ResizeToContents)):
            header.setSectionResizeMode(column, mode)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 110)
        table_card = QFrame(objectName="TableCard")
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.addWidget(self.table)

        self.detail = FormulaDetail()

        tools = QHBoxLayout()
        tools.addWidget(self.search, 1)
        tools.addWidget(self.count)
        tools.addStretch(1)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(table_card, 1)
        body.addWidget(self.detail)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addLayout(tools)
        layout.addLayout(self.chips_row)
        layout.addLayout(body, 1)

        self.search.textChanged.connect(self.refresh_rows)
        self.table.itemSelectionChanged.connect(self._on_selected)

    # ------------------------------------------------------------- loading
    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self._loaded:
            self.load()

    def load(self) -> None:
        """Read the formulas (built into the app, so this is instant) and build the chips and rows."""
        self.formulas = list(self._facade.list_formulas())
        self._loaded = True
        categories = [category for category, _ in self._facade.formula_categories()]
        descriptions = dict(self._facade.formula_categories())
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.chips = {}
        for category in [ALL, *categories]:
            count = len(self.formulas) if category == ALL else \
                sum(1 for formula in self.formulas if formula.category == category)
            chip = QPushButton(f"{category}  {count}", objectName="CategoryChip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(descriptions.get(category, "Every category"))
            if category != ALL:
                colour = CATEGORY_COLOURS.get(category, theme.OCEAN)
                chip.setStyleSheet(f"QPushButton#CategoryChip {{ border-left: 4px solid {colour}; }}")
            chip.clicked.connect(lambda _=False, category=category: self.set_category(category))
            self.chip_group.addButton(chip)
            self.chips_row.addWidget(chip)
            self.chips[category] = chip
        self.chips_row.addStretch(1)
        self.chips[ALL].setChecked(True)
        self.refresh_rows()

    def set_category(self, category: str) -> None:
        self.category = category
        if category in self.chips:
            self.chips[category].setChecked(True)
        self.refresh_rows()

    # ------------------------------------------------------------- rows
    def visible_formulas(self) -> list[FormulaDTO]:
        query = self.search.text().strip()
        return [formula for formula in self.formulas
                if (self.category == ALL or formula.category == self.category) and matches(formula, query)]

    def refresh_rows(self) -> None:
        shown = self.visible_formulas()
        self.table.setRowCount(0)
        self._row_formulas: dict[int, FormulaDTO] = {}
        current = None
        for formula in shown:
            if formula.category != current:  # a group row before each category
                current = formula.category
                self._add_group_row(current)
            self._add_row(formula)
        self.table.resizeRowsToContents()
        self.count.setText(f"{len(shown)} of {len(self.formulas)} shown")
        self.detail.show_formula(shown[0] if len(shown) == 1 else None)

    def _add_group_row(self, category: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(category.upper())
        font = QFont(theme.SANS, 9)
        font.setBold(True)
        item.setFont(font)
        colour = CATEGORY_COLOURS.get(category, theme.OCEAN)
        item.setForeground(QColor(colour))
        item.setBackground(QColor(theme.FIELD_BG))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable
        self.table.setItem(row, 0, item)
        self.table.setSpan(row, 0, 1, len(COLUMNS))

    def _add_row(self, formula: FormulaDTO) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._row_formulas[row] = formula
        values = (formula.key, formula.name, formula.formula, band_text(formula), formula.value_range,
                  "; ".join(formula.use_cases), "Yes" if formula.computable else "Reference")
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setToolTip(text if column != 0 else f"{formula.name}\n{formula.formula}")
            if column == 0:
                font = QFont(theme.SANS, 10)
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QColor(CATEGORY_COLOURS.get(formula.category, theme.INK)))
            elif column == 2:
                item.setFont(QFont(FORMULA_FONT, 10))
            elif column == 6:
                item.setForeground(QColor(theme.SUCCESS if formula.computable else theme.MUTED))
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.table.setItem(row, column, item)

    def formula_at(self, row: int) -> FormulaDTO | None:
        return getattr(self, "_row_formulas", {}).get(row)

    def _on_selected(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        formula = self.formula_at(min(rows)) if rows else None
        if formula is not None:
            self.detail.show_formula(formula)

    def select_formula(self, key: str) -> bool:
        """Select the row of ``key`` (e.g. from a link elsewhere); False if it is not shown."""
        for row, formula in getattr(self, "_row_formulas", {}).items():
            if formula.key == key:
                self.table.selectRow(row)
                return True
        return False
