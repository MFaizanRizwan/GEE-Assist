"""Small charts of a project's analyses for the dashboard, drawn with QPainter in the theme's colours.

* ``CategoryBarChart``: how many analyses of each type ran, as horizontal bars, each labelled on
  the left (left-aligned) with its count at the end of the bar.
* ``MetricTrendChart``: how one number (e.g. "NDVI mean") changed over the project's analyses,
  oldest to newest, as a line with a dot per analysis.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from frontend import fonts, theme

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
        font.setPointSizeF(fonts.SM)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        if not self.counts:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRectF(PADDING, 0, self.width() - 2 * PADDING, self.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "No analyses yet")
            return
        colours = _bar_colours()
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


TREND_HEIGHT = 190
AXIS_WIDTH = 56                                 # room for the values, left of the plot
DATE_ROW = 18                                   # room for the first and last date, under the plot


class MetricTrendChart(QWidget):
    """One number across a project's analyses, oldest to newest: a line with a dot per analysis,
    its highest and lowest values on the left and the first and last dates underneath."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.name = ""
        self.points: list[tuple[str, float]] = []
        self.setFixedHeight(TREND_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_series(self, name: str, points: list[tuple[str, float]]) -> None:
        """``points``: (date shown, value) pairs, oldest first."""
        self.name = name
        self.points = [(when, float(value)) for when, value in points]
        self.setToolTip("\n".join(f"{when}: {value:.4g}" for when, value in self.points) or "No values yet")
        self.setAccessibleDescription(f"{name} over {len(self.points)} analyses" if self.points else "No values yet")
        self.update()

    def plot_rect(self) -> QRectF:
        return QRectF(PADDING + AXIS_WIDTH, PADDING, self.width() - 2 * PADDING - AXIS_WIDTH,
                      self.height() - 2 * PADDING - DATE_ROW)

    def point_positions(self) -> list[QPointF]:
        """Where each value is drawn (for tests): left to right in order, higher values higher up."""
        if not self.points:
            return []
        plot = self.plot_rect()
        values = [value for _, value in self.points]
        low, high = min(values), max(values)
        span = (high - low) or 1.0
        step = plot.width() / max(1, len(values) - 1)
        middle = plot.top() + plot.height() / 2
        return [QPointF(plot.left() + (step * index if len(values) > 1 else plot.width() / 2),
                        middle if high == low else plot.bottom() - (value - low) / span * plot.height())
                for index, value in enumerate(values)]

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if not _fieldbook():  # Layout 3 draws the chart straight on the page: no frame inside the panel
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.setBrush(QColor(theme.FIELD_BG))
            painter.drawRoundedRect(area, 8, 8)
        font = QFont(self.font())
        font.setPointSizeF(fonts.XS)
        painter.setFont(font)
        plot = self.plot_rect()
        left_aligned = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if len(self.points) < 2:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(area.adjusted(PADDING, 0, -PADDING, 0), left_aligned,
                             "Run this analysis again to see how its numbers change." if self.points
                             else "No values yet")
            painter.end()
            return

        painter.setPen(QPen(QColor(theme.CHART_GRID), 1, Qt.PenStyle.DashLine))
        for step in (0.0, 0.5, 1.0):
            y = plot.top() + plot.height() * step
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        values = [value for _, value in self.points]
        painter.setPen(QColor(theme.MUTED))
        for value, y in ((max(values), plot.top()), (min(values), plot.bottom())):
            painter.drawText(QRectF(PADDING, y - 8, AXIS_WIDTH - 6, 16), left_aligned, f"{value:.3g}")
        under = QRectF(plot.left(), plot.bottom() + 4, plot.width(), DATE_ROW)
        painter.drawText(under, left_aligned, self.points[0][0])
        painter.drawText(under, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.points[-1][0])

        positions = self.point_positions()
        line = QPainterPath(positions[0])
        for point in positions[1:]:
            line.lineTo(point)
        painter.setPen(QPen(QColor(_line_colour()), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.INK if _fieldbook() else theme.LEAF))
        for point in positions:
            painter.drawEllipse(point, 3.5, 3.5)
        painter.end()


def _fieldbook() -> bool:
    from frontend import fieldbook  # late: fieldbook imports theme

    return fieldbook.active()


def _bar_colours() -> tuple[str, str]:
    """Layout 3 keeps colour for the result maps: bars are the book's yellow and ink."""
    if _fieldbook():
        from frontend import fieldbook

        return fieldbook.SPINE, theme.MUTED
    return theme.LEAF, theme.OCEAN


def _line_colour() -> str:
    if _fieldbook():
        from frontend import fieldbook

        return fieldbook.SPINE
    return theme.OCEAN
