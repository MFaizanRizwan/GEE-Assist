"""An on/off switch with its label: a rounded track with a knob that sits right when on."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from frontend import theme

TRACK_WIDTH = 34
TRACK_HEIGHT = 18
GAP = 9


class ToggleSwitch(QAbstractButton):
    """A checkable button drawn as a switch. ``toggled(bool)`` says when it is flipped."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(TRACK_WIDTH + (GAP + text_width if self.text() else 0) + 2,
                     max(TRACK_HEIGHT, self.fontMetrics().height()) + 4)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = (self.height() - TRACK_HEIGHT) / 2
        track = QRectF(1, top, TRACK_WIDTH, TRACK_HEIGHT)
        on = self.isChecked()
        colour = QColor(theme.LEAF if on else theme.BORDER_STRONG)
        if not self.isEnabled():
            colour.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawRoundedRect(track, TRACK_HEIGHT / 2, TRACK_HEIGHT / 2)
        knob = TRACK_HEIGHT - 4
        x = track.right() - knob - 2 if on else track.left() + 2
        painter.setBrush(QColor(theme.WHITE))
        painter.drawEllipse(QRectF(x, top + 2, knob, knob))
        if self.hasFocus():
            painter.setPen(QColor(theme.OCEAN))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), TRACK_HEIGHT / 2 + 1, TRACK_HEIGHT / 2 + 1)
        if self.text():
            painter.setPen(QColor(theme.INK if self.isEnabled() else theme.MUTED))
            text_rect = QRectF(track.right() + GAP, 0, self.width() - track.right() - GAP, self.height())
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        painter.end()
