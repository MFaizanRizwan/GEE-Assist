"""Small charts of a project's analyses for the dashboard, drawn with QPainter in the theme's colours.

* ``CategoryBarChart``: how many analyses of each type ran, as horizontal bars, each labelled on
  the left (left-aligned) with its count at the end of the bar.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from frontend import theme

BAR_HEIGHT = 16
BAR_GAP = 10
LABEL_WIDTH = 150                               # room for the type's name, left of its bar
PADDING = 12


class CategoryBarChart(QWidget):
    """Horizontal bars: one per analysis type, as long as the number of analyses of that type."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.counts: list[tuple[str, int]] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_counts([])

    def set_counts(self, counts: list[tuple[str, int]]) -> None:
        """(type, number of analyses) pairs, drawn in the order given."""
        self.counts = [(label, int(count)) for label, count in counts if count > 0]
        rows = max(1, len(self.counts))
        self.setFixedHeight(2 * PADDING + rows * BAR_HEIGHT + (rows - 1) * BAR_GAP)
        total = sum(count for _, count in self.counts)
        self.setToolTip("\n".join(f"{label}: {count}" for label, count in self.counts) or "No analyses yet")
        self.setAccessibleDescription(f"{total} analyses: " + ", ".join(f"{count} {label}" for label, count in self.counts)
                                      if self.counts else "No analyses yet")
        self.update()

    def bar_rects(self) -> list[QRectF]:
        """Where each bar is drawn (for tests): its length is proportional to its count."""
        if not self.counts:
            return []
        top = max(count for _, count in self.counts)
        left = PADDING + LABEL_WIDTH
        room = max(1.0, self.width() - left - PADDING - 36)  # 36: the count after the longest bar
        return [QRectF(left, PADDING + index * (BAR_HEIGHT + BAR_GAP), room * count / top, BAR_HEIGHT)
                for index, (_, count) in enumerate(self.counts)]

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(9)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        if not self.counts:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRectF(PADDING, 0, self.width() - 2 * PADDING, self.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "No analyses yet")
            return
        colours = (theme.LEAF, theme.OCEAN)
        for index, ((label, count), bar) in enumerate(zip(self.counts, self.bar_rects())):
            painter.setPen(QColor(theme.TEXT))
            name = metrics.elidedText(label, Qt.TextElideMode.ElideRight, LABEL_WIDTH - 10)
            painter.drawText(QRectF(PADDING, bar.top(), LABEL_WIDTH - 10, BAR_HEIGHT),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colours[index % len(colours)]))
            painter.drawRoundedRect(bar, 4, 4)
            painter.setPen(QPen(QColor(theme.INK)))
            painter.drawText(QRectF(bar.right() + 6, bar.top(), 40, BAR_HEIGHT),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(count))
        painter.end()
