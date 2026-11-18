"""A value shown as text that becomes a text box when clicked.

It only counts as changed (``is_dirty``) when the typed text differs from the value; leaving
the box without changing anything shows the plain text again, and Esc gives up the change.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from frontend import theme

_ROW_HEIGHT = 38


class InlineEdit(QWidget):
    changed = pyqtSignal()    # the text was edited, or the edit was given up: is_dirty() may differ
    submitted = pyqtSignal()  # Enter in the text box

    def __init__(self, placeholder: str = "—", hint: str = "Click to change", parent: QWidget | None = None):
        super().__init__(parent)
        self._value = ""
        self._placeholder = placeholder

        self.display = QPushButton(objectName="InlineValue")
        self.display.setCursor(Qt.CursorShape.IBeamCursor)
        self.display.setToolTip(hint)
        self.display.setFlat(True)
        self.display.setStyleSheet(
            f"QPushButton#InlineValue {{ text-align: left; color: {theme.INK}; background: transparent;"
            f" border: 1px solid transparent; border-radius: 8px; padding: 6px 10px; font-weight: 400; }}"
            f"QPushButton#InlineValue:hover {{ background: {theme.FOAM}; border-color: {theme.BORDER}; }}"
        )
        self.input = QLineEdit()
        self.input.setStyleSheet("QLineEdit { padding: 6px 10px; }")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.display)
        self.stack.addWidget(self.input)
        self.stack.setFixedHeight(_ROW_HEIGHT)
        self.error = QLabel(objectName="FieldError")
        self.error.setWordWrap(True)
        self.error.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.stack)
        layout.addWidget(self.error)

        self.display.clicked.connect(self.start_editing)
        self.input.textEdited.connect(self._on_text_edited)
        self.input.returnPressed.connect(self.submitted)
        self.input.installEventFilter(self)

    # ------------------------------------------------------------- value
    def set_value(self, value: str | None) -> None:
        """The saved value. A change being typed is kept."""
        self._value = value or ""
        self.display.setText(self._value or self._placeholder)
        if not self.is_dirty():
            self.input.setText(self._value)

    def value(self) -> str:
        return self.input.text() if self.is_editing() else self._value

    def is_editing(self) -> bool:
        return self.stack.currentWidget() is self.input

    def is_dirty(self) -> bool:
        return self.is_editing() and self.input.text().strip() != self._value

    # ------------------------------------------------------------- editing
    def start_editing(self) -> None:
        self.input.setText(self._value)
        self.stack.setCurrentWidget(self.input)
        self.input.setFocus(Qt.FocusReason.MouseFocusReason)
        self.input.selectAll()

    def discard(self) -> None:
        """Back to the saved value, shown as text."""
        self.input.setText(self._value)
        self.clear_error()
        self.stack.setCurrentWidget(self.display)
        self.changed.emit()

    def set_error(self, message: str) -> None:
        if not self.is_editing():
            self.start_editing()
        self.error.setText(message)
        self.error.show()
        self.input.setProperty("invalid", True)
        self._repolish()

    def clear_error(self) -> None:
        self.error.hide()
        if self.input.property("invalid"):
            self.input.setProperty("invalid", False)
            self._repolish()

    def _on_text_edited(self, _text: str) -> None:
        self.clear_error()
        self.changed.emit()

    def _repolish(self) -> None:
        self.input.style().unpolish(self.input)
        self.input.style().polish(self.input)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if watched is self.input:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.discard()
                return True
            if event.type() == QEvent.Type.FocusOut and not self.is_dirty() and not self.error.isVisible():
                self.stack.setCurrentWidget(self.display)  # nothing changed: plain text again
        return super().eventFilter(watched, event)
