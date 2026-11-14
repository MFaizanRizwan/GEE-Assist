"""Choosing an analysis and its processes, on the Analysis page.

* ``AnalysisTile``: one of the four analyses (water, vegetation, LST, LULC) with its
  sub-types and how many of its processes the dataset can run.
* ``ProcessCard``: one process as a card that is clicked (or Space) to select it: its
  key, name and formula, a check circle when selected, and a "before / after" badge
  for processes that compare two dates. A card that cannot run is dimmed, shows why
  instead of the formula, and cannot be selected.
* ``ProcessPicker``: the cards of one analysis. Those that can run come first,
  grouped by sub-type; those that cannot are in a separate section below, folded
  away until opened. Sub-type chips narrow the cards; "Select all" / "Clear" act on
  the ones that can run.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from backend.dto.analysis_dto import AnalysisOptionDTO, FormulaDTO, ProcessOptionDTO
from frontend import theme

ALL = "All"
CHIP_ROW_WIDTH = 320  # sub-type chips start a new row beyond this (the panel is narrow)
FORMULA_FONT = "Cambria Math"

# A colour per analysis (tiles, chips, the selected-card border).
ANALYSIS_COLOURS: dict[str, str] = {
    "Water": "#2F7CC4",
    "Vegetation": "#3E9B4F",
    "LST": "#D9534F",
    "LULC": "#8C6239",
}

STYLESHEET = f"""
QPushButton#AnalysisTile {{
    text-align: left; border: 1px solid {theme.BORDER_STRONG}; border-radius: 10px; padding: 8px 10px;
    background: {theme.WHITE}; color: {theme.INK};
}}
QPushButton#AnalysisTile:hover {{ background: {theme.FOAM}; }}
QPushButton#AnalysisTile:checked {{ background: {theme.MINT}; border: 2px solid {theme.LEAF}; }}
QPushButton#AnalysisTile:disabled {{ color: {theme.SUBTLE}; background: {theme.TILE_DISABLED_BG}; }}
QFrame#ProcessCard {{
    background: {theme.WHITE}; border: 1px solid {theme.BORDER}; border-radius: 10px;
}}
QFrame#ProcessCard[available="true"]:hover {{ background: {theme.FOAM}; border-color: {theme.BORDER_HOVER}; }}
QFrame#ProcessCard[selected="true"] {{ background: {theme.FOAM}; border: 2px solid {theme.LEAF}; }}
QFrame#ProcessCard[available="false"] {{ background: {theme.TILE_DISABLED_BG}; border: 1px dashed {theme.BORDER}; }}
QFrame#ProcessCard QLabel {{ background: transparent; border: none; }}
QLabel#CardKey {{ color: {theme.INK}; font-weight: 700; font-size: 10pt; }}
QFrame#ProcessCard[available="false"] QLabel#CardKey {{ color: {theme.MUTED}; }}
QLabel#CardName {{ color: {theme.TEXT}; font-size: 9pt; }}
QLabel#CardFormula {{ color: {theme.MUTED}; font-family: "{FORMULA_FONT}", "{theme.SERIF}"; font-size: 9pt; }}
QLabel#CardReason {{ color: {theme.ERROR}; font-size: 8.5pt; }}
QLabel#CardCheck {{
    border: 1.5px solid {theme.BORDER_STRONG}; border-radius: 10px; background: {theme.WHITE};
    color: {theme.WHITE}; font-weight: 700; font-size: 9pt;
}}
QLabel#CardCheck[on="true"] {{ background: {theme.LEAF}; border-color: {theme.LEAF}; }}
QLabel#CardBadge {{
    color: {theme.OCEAN_DARK}; background: {theme.INFO_BG}; border: 1px solid {theme.INFO_BORDER};
    border-radius: 8px; padding: 0 6px; font-size: 8pt;
}}
QLabel#GroupTitle {{ color: {theme.MUTED}; font-size: 8.5pt; font-weight: 700; letter-spacing: 0.5px; }}
QLabel#SectionCan {{ color: {theme.SUCCESS}; font-weight: 700; }}
QPushButton#SectionCannot {{
    color: {theme.MUTED}; font-weight: 700; border: none; background: transparent; padding: 2px 0;
    text-align: left; font-size: 10pt;
}}
QPushButton#SectionCannot:hover {{ color: {theme.INK}; }}
QPushButton#SubtypeChip {{
    border: 1px solid {theme.BORDER_STRONG}; border-radius: 12px; padding: 3px 10px; font-size: 8.5pt;
    font-weight: 600; background: {theme.WHITE}; color: {theme.INK};
}}
QPushButton#SubtypeChip:hover {{ background: {theme.FOAM}; }}
QPushButton#SubtypeChip:checked {{ background: {theme.MINT}; border-color: {theme.LEAF}; }}
"""


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _shrinkable(widget: QWidget) -> QWidget:
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, widget.sizePolicy().verticalPolicy())
    return widget


class AnalysisTile(QPushButton):
    """One of the four analyses: its name, sub-types and how many processes can run."""

    def __init__(self, option: AnalysisOptionDTO, parent: QWidget | None = None):
        count = sum(1 for p in option.processes if p.available)
        title = option.label or option.category
        super().__init__(f"{title}\n{count} of {len(option.processes)} can run", parent)
        self.option = option
        self.setObjectName("AnalysisTile")
        self.setCheckable(True)
        self.setEnabled(option.available)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(52)
        _shrinkable(self)
        colour = ANALYSIS_COLOURS.get(option.category, theme.OCEAN)
        self.setStyleSheet(f"QPushButton#AnalysisTile {{ border-left: 5px solid {colour}; }}")
        subtypes = " · ".join(option.subtypes)
        self.setToolTip(f"{option.description}\nSub-types: {subtypes}" if option.available else
                        f"{option.description}\nThis dataset has none of the bands it needs.")


class ProcessCard(QFrame):
    """A process to pick: click or press Space to select it (only when it can run)."""

    toggled = pyqtSignal(bool)

    def __init__(self, process: ProcessOptionDTO, formula: FormulaDTO | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.process = process
        self.key = process.key
        self._selected = False
        self.setObjectName("ProcessCard")
        self.setProperty("available", process.available)
        self.setProperty("selected", False)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        _shrinkable(self)

        self.check = QLabel("", objectName="CardCheck")
        self.check.setFixedSize(20, 20)
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.setProperty("on", False)
        self.check.setVisible(process.available)
        key = QLabel(process.key, objectName="CardKey")
        name = QLabel(process.label if process.label != process.key else "", objectName="CardName")
        name.setWordWrap(True)
        if process.available:
            detail = QLabel(formula.formula if formula else "", objectName="CardFormula")
        else:
            detail = QLabel(f"✕  {process.reason}", objectName="CardReason")
        detail.setWordWrap(True)
        for label in (name, detail):
            _shrinkable(label)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(key)
        if process.periods > 1:
            top.addWidget(QLabel("before / after", objectName="CardBadge"))
        top.addStretch(1)
        top.addWidget(self.check)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        layout.addLayout(top)
        if name.text():
            layout.addWidget(name)
        if detail.text():
            layout.addWidget(detail)

        tip = formula.name if formula else process.label
        if formula and formula.use_cases:
            tip += "\nUse: " + "; ".join(formula.use_cases[:3])
        if process.available:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setToolTip(tip + "\n\nClick to select.")
        else:
            self.setToolTip(f"{tip}\n\nCannot run on this dataset: {process.reason}")

    @property
    def available(self) -> bool:
        return self.process.available

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        selected = selected and self.available
        if selected == self._selected:
            return
        self._selected = selected
        self.setProperty("selected", selected)
        self.check.setProperty("on", selected)
        self.check.setText("✓" if selected else "")
        _repolish(self)
        _repolish(self.check)
        self.toggled.emit(selected)

    def toggle(self) -> None:
        self.set_selected(not self._selected)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.toggle()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
            return
        super().keyPressEvent(event)


class ProcessPicker(QWidget):
    """The processes of one analysis: those that can run, then (folded) those that cannot."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(STYLESHEET)
        self.option: AnalysisOptionDTO | None = None
        self.cards: dict[str, ProcessCard] = {}
        self.subtype = ALL

        self.count_label = QLabel(objectName="Muted")
        self.select_all_button = QPushButton("Select all", objectName="LinkButton")
        self.clear_button = QPushButton("Clear", objectName="LinkButton")
        for button in (self.select_all_button, self.clear_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        tools = QHBoxLayout()
        tools.addWidget(_shrinkable(self.count_label), 1)
        tools.addWidget(self.select_all_button)
        tools.addWidget(self.clear_button)

        self.chips_box = QWidget()
        self.chips = QVBoxLayout(self.chips_box)  # rows of chips, so they wrap in the narrow panel
        self.chips.setContentsMargins(0, 0, 0, 0)
        self.chips.setSpacing(4)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chip_buttons: dict[str, QPushButton] = {}

        self.can_title = _shrinkable(QLabel(objectName="SectionCan"))
        self.can_area = QVBoxLayout()
        self.can_area.setSpacing(6)
        self.cannot_toggle = _shrinkable(QPushButton(objectName="SectionCannot"))
        self.cannot_toggle.setCheckable(True)
        self.cannot_toggle.setChecked(False)
        self.cannot_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cannot_box = QWidget()
        self.cannot_area = QVBoxLayout(self.cannot_box)
        self.cannot_area.setContentsMargins(0, 0, 0, 0)
        self.cannot_area.setSpacing(6)
        self.cannot_box.hide()
        self.empty = QLabel("Choose a dataset and an analysis.", objectName="Muted")
        self.empty.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.empty)
        layout.addLayout(tools)
        layout.addWidget(self.chips_box)
        layout.addWidget(self.can_title)
        layout.addLayout(self.can_area)
        layout.addSpacing(4)
        layout.addWidget(self.cannot_toggle)
        layout.addWidget(self.cannot_box)

        self.select_all_button.clicked.connect(self.select_all)
        self.clear_button.clicked.connect(self.clear)
        self.cannot_toggle.toggled.connect(self._show_cannot)
        self.set_option(None)

    # ------------------------------------------------------------- content
    def set_option(self, option: AnalysisOptionDTO | None, formulas: dict[str, FormulaDTO] | None = None,
                   selected: list[str] | None = None) -> None:
        """Show ``option``'s processes; ``selected`` (if it can run) or the first that can run is selected."""
        self.option = option
        formulas = formulas or {}
        for area in (self.can_area, self.cannot_area, self.chips):
            _clear(area)
        for button in list(self.chip_group.buttons()):
            self.chip_group.removeButton(button)
        self.cards, self.chip_buttons, self.subtype = {}, {}, ALL
        has = option is not None and bool(option.processes)
        for widget in (self.select_all_button, self.clear_button, self.count_label, self.can_title,
                       self.chips_box):
            widget.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            self.cannot_toggle.hide()
            self.cannot_box.hide()
            self.changed.emit()
            return

        can = [p for p in option.processes if p.available]
        cannot = [p for p in option.processes if not p.available]
        self.can_title.setText(f"●  Can run on this dataset ({len(can)})" if can else
                               "No process of this analysis can run on this dataset.")
        self._fill(self.can_area, can, formulas)
        self._fill(self.cannot_area, cannot, formulas)
        self.cannot_toggle.setVisible(bool(cannot))
        self._update_cannot_title(len(cannot))
        self._fill_chips(option)

        wanted = [key for key in (selected or []) if key in self.cards and self.cards[key].available]
        if not wanted and can:
            wanted = [can[0].key]
        for key in wanted:
            self.cards[key].set_selected(True)
        self._update_count()
        self.changed.emit()

    def _fill(self, area: QVBoxLayout, processes: list[ProcessOptionDTO], formulas: dict[str, FormulaDTO]) -> None:
        order = list(self.option.subtypes) if self.option else []
        groups = sorted({p.group for p in processes}, key=lambda g: order.index(g) if g in order else len(order))
        for group in groups:
            title = _shrinkable(QLabel(group.upper() if group else "OTHER", objectName="GroupTitle"))
            title.setProperty("group", group)
            area.addWidget(title)
            for process in (p for p in processes if p.group == group):
                card = ProcessCard(process, formulas.get(process.key))
                card.toggled.connect(self._on_card_toggled)
                area.addWidget(card)
                self.cards[process.key] = card

    def _fill_chips(self, option: AnalysisOptionDTO) -> None:
        present = [sub for sub in option.subtypes if any(p.group == sub for p in option.processes)]
        if len(present) < 2:
            self.chips_box.hide()
            return
        row, width = None, 0
        for name in [ALL, *present]:
            count = len(option.processes) if name == ALL else sum(1 for p in option.processes if p.group == name)
            available = sum(1 for p in option.processes if p.available and (name == ALL or p.group == name))
            chip = QPushButton(f"{name}  {available}/{count}", objectName="SubtypeChip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"Show {'every sub-type' if name == ALL else name}: {available} of {count} can run")
            chip.clicked.connect(lambda _=False, name=name: self.show_subtype(name))
            self.chip_group.addButton(chip)
            hint = chip.sizeHint().width() + 4
            if row is None or width + hint > CHIP_ROW_WIDTH:
                row = QHBoxLayout()
                row.setSpacing(4)
                self.chips.addLayout(row)
                width = 0
            row.addWidget(chip)
            width += hint
            self.chip_buttons[name] = chip
        for index in range(self.chips.count()):
            item = self.chips.itemAt(index)
            if item.layout() is not None:
                item.layout().addStretch(1)
        self.chip_buttons[ALL].setChecked(True)

    def show_subtype(self, name: str) -> None:
        """Show only the cards (and group titles) of one sub-type, or all of them."""
        self.subtype = name
        if name in self.chip_buttons:
            self.chip_buttons[name].setChecked(True)
        for area in (self.can_area, self.cannot_area):
            for index in range(area.count()):
                widget = area.itemAt(index).widget()
                if widget is None:
                    continue
                group = widget.property("group") if not isinstance(widget, ProcessCard) else widget.process.group
                widget.setVisible(name == ALL or group == name)
        self._update_count()

    # ------------------------------------------------------------- selection
    def selected(self) -> list[str]:
        return [key for key, card in self.cards.items() if card.is_selected()]

    def selected_options(self) -> list[ProcessOptionDTO]:
        return [card.process for card in self.cards.values() if card.is_selected()]

    def set_selected(self, keys: list[str]) -> None:
        for key, card in self.cards.items():
            card.set_selected(key in keys)

    def select_all(self) -> None:
        """Select every process that can run (of the sub-type shown)."""
        for card in self.cards.values():
            if card.available and (self.subtype == ALL or card.process.group == self.subtype):
                card.set_selected(True)

    def clear(self) -> None:
        for card in self.cards.values():
            card.set_selected(False)

    def _on_card_toggled(self, _selected: bool) -> None:
        self._update_count()
        self.changed.emit()

    def _update_count(self) -> None:
        chosen = len(self.selected())
        self.count_label.setText(f"{chosen} selected" if chosen else "Nothing selected: click a card")

    # ------------------------------------------------------------- the "cannot run" section
    def _show_cannot(self, shown: bool) -> None:
        self.cannot_box.setVisible(shown)
        self._update_cannot_title(sum(1 for card in self.cards.values() if not card.available))

    def _update_cannot_title(self, count: int) -> None:
        arrow = "▾" if self.cannot_toggle.isChecked() else "▸"
        self.cannot_toggle.setText(f"{arrow}  Can't run on this dataset ({count})")
        self.cannot_toggle.setToolTip("Show or hide the processes this dataset's bands cannot compute, and why")


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())
