"""Small drawn icons for the side bar, each with a looping animation.

An icon is drawn for a moment ``t`` of its loop (0 to 1). At rest (not hovered) it is
drawn at ``t = None``: a still picture. Colours come from the theme, so the icons
follow light and dark themes.

* ``DownloadIcon``: an arrow over a tray; animated, the arrow slides down into the
  tray and comes back in from the top (it wraps around).
* ``WritingIcon``: a sheet of paper and a pencil; animated, the pencil writes the
  lines on the paper one after another.
* ``TerminalIcon``: a terminal window with a prompt; animated, characters are typed
  after the prompt while the cursor blinks.
* ``AnalysisIcon``: three bars of a spectral chart under a magnifying lens; animated,
  the bars rise and fall in a wave while the lens sweeps back and forth over them,
  colouring the bar it is examining.
* ``ExplainIcon``: a speech bubble with a sparkle (AI explanation); animated, the explanation's
  lines appear in the bubble one after another while the sparkle twinkles.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen

from frontend import theme


# Layout 3 draws the side bar as a graphite cover in every theme, so its icons take the cover's
# colours there; elsewhere they take the theme's.
def _ink() -> str:
    from frontend import fieldbook

    return fieldbook.cover_text() if fieldbook.active() else theme.INK


def _muted() -> str:
    from frontend import fieldbook

    return fieldbook.cover_muted() if fieldbook.active() else theme.MUTED


def _paper() -> str:
    from frontend import fieldbook

    return fieldbook.cover_raised() if fieldbook.active() else theme.WHITE


class SideIcon:
    """An icon drawn in a square ``rect``; ``period_ms`` is the length of one animation loop."""

    period_ms = 1200

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        raise NotImplementedError


class DownloadIcon(SideIcon):
    period_ms = 1100

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        pen = QPen(QColor(_ink()), max(1.6, s * 0.09), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Tray: a U along the bottom.
        painter.setPen(pen)
        tray_top, bottom = rect.top() + s * 0.62, rect.top() + s * 0.86
        tray = QPainterPath(QPointF(rect.left() + s * 0.14, tray_top))
        tray.lineTo(rect.left() + s * 0.14, bottom)
        tray.lineTo(rect.right() - s * 0.14, bottom)
        tray.lineTo(rect.right() - s * 0.14, tray_top)
        painter.drawPath(tray)

        # Arrow: slides down by one "lane" per loop; a second copy above makes it wrap around.
        lane = QRectF(rect.left(), rect.top(), s, s * 0.74)  # the arrow is only seen above the tray's floor
        travel = lane.height()
        offset = (t or 0.0) * travel
        painter.setClipRect(lane)
        arrow_pen = QPen(pen)
        arrow_pen.setColor(QColor(theme.LEAF))
        painter.setPen(arrow_pen)
        for shift in (offset, offset - travel):
            self._arrow(painter, rect, shift)
        painter.restore()

    @staticmethod
    def _arrow(painter: QPainter, rect: QRectF, shift: float) -> None:
        s, x = rect.width(), rect.center().x()
        top, tip = rect.top() + s * 0.12 + shift, rect.top() + s * 0.6 + shift
        painter.drawLine(QPointF(x, top), QPointF(x, tip))
        head = QPainterPath(QPointF(x - s * 0.2, tip - s * 0.2))
        head.lineTo(x, tip)
        head.lineTo(x + s * 0.2, tip - s * 0.2)
        painter.drawPath(head)

    @staticmethod
    def arrow_tip(rect: QRectF, t: float | None) -> float:
        """Where the arrow's tip is at moment ``t`` (for tests): it moves down, then wraps."""
        s = rect.width()
        return rect.top() + s * 0.6 + (t or 0.0) * s * 0.74


class WritingIcon(SideIcon):
    period_ms = 2100
    LINES = 3

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.4, s * 0.075)
        pen = QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Paper.
        paper = QRectF(rect.left() + s * 0.08, rect.top() + s * 0.06, s * 0.62, s * 0.86)
        painter.setPen(pen)
        painter.setBrush(QColor(_paper()))
        painter.drawRoundedRect(paper, s * 0.08, s * 0.08)

        # Writing: at rest every line is written; animated, the lines are written one by one.
        writing = QPen(QColor(_muted()), line_width * 0.85, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(writing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        tip = None
        for line in range(self.LINES):
            done = self.line_progress(t, line)
            if done <= 0:
                continue
            start, end = self._line_ends(paper, line)
            length = (end.x() - start.x()) * done
            path = QPainterPath(start)
            steps = max(2, int(length / max(1.0, s * 0.04)))
            for step in range(1, steps + 1):
                x = start.x() + length * step / steps
                path.lineTo(x, start.y() + math.sin((x - start.x()) / (s * 0.05)) * s * 0.025)  # handwriting
            painter.drawPath(path)
            if 0 < done < 1 or t is None:
                tip = path.currentPosition()
        if tip is None:  # between lines: the pencil waits at the start of the next one
            tip, _ = self._line_ends(paper, min(self.LINES - 1, int((t or 0) * self.LINES)))

        self._pencil(painter, rect, tip, line_width)
        painter.restore()

    @classmethod
    def line_progress(cls, t: float | None, line: int) -> float:
        """How much of ``line`` is written at moment ``t`` (0 to 1). At rest, all of it."""
        if t is None:
            return 1.0
        return min(1.0, max(0.0, t * cls.LINES - line))

    @staticmethod
    def _line_ends(paper: QRectF, line: int) -> tuple[QPointF, QPointF]:
        y = paper.top() + paper.height() * (0.3 + 0.22 * line)
        return QPointF(paper.left() + paper.width() * 0.2, y), QPointF(paper.right() - paper.width() * 0.2, y)

    @staticmethod
    def _pencil(painter: QPainter, rect: QRectF, tip: QPointF, line_width: float) -> None:
        """A pencil leaning to the right, its point at ``tip``."""
        s = rect.width()
        painter.save()
        painter.translate(tip)
        painter.rotate(-45)  # the pencil points down-left, its body up-right
        length, width = s * 0.62, s * 0.2
        body = QRectF(width * 0.9, -width / 2, length - width * 0.9, width)
        painter.setPen(QPen(QColor(_ink()), line_width * 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(theme.OCEAN))
        painter.drawRoundedRect(body, width * 0.25, width * 0.25)
        point = QPainterPath(QPointF(0, 0))  # sharpened end
        point.lineTo(width * 0.9, -width / 2)
        point.lineTo(width * 0.9, width / 2)
        point.closeSubpath()
        painter.setBrush(QColor(_paper()))
        painter.drawPath(point)
        painter.restore()


class TerminalIcon(SideIcon):
    period_ms = 1600
    CHARACTERS = 3   # typed after the prompt in one loop
    BLINKS = 4       # times the cursor blinks in one loop

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.4, s * 0.075)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # The window.
        window = QRectF(rect.left() + s * 0.06, rect.top() + s * 0.14, s * 0.88, s * 0.72)
        painter.setPen(QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(window, s * 0.1, s * 0.1)

        # The prompt: ">".
        left, middle = window.left() + s * 0.14, window.center().y()
        prompt = QPainterPath(QPointF(left, middle - s * 0.12))
        prompt.lineTo(left + s * 0.12, middle)
        prompt.lineTo(left, middle + s * 0.12)
        painter.setPen(QPen(QColor(theme.LEAF), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(prompt)

        # What is typed (short strokes), then the cursor: "_".
        baseline = middle + s * 0.12
        x = left + s * 0.22
        step = s * 0.13
        painter.setPen(QPen(QColor(_muted()), line_width * 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for _ in range(self.typed(t)):
            painter.drawLine(QPointF(x, baseline - s * 0.05), QPointF(x + s * 0.06, baseline - s * 0.05))
            x += step
        if self.cursor_visible(t):
            painter.setPen(QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x, baseline), QPointF(x + s * 0.12, baseline))
        painter.restore()

    @classmethod
    def typed(cls, t: float | None) -> int:
        """Characters typed at moment ``t``: none at rest, then one more each step of the loop."""
        if t is None:
            return 0
        return min(cls.CHARACTERS, int(t * (cls.CHARACTERS + 1)))

    @classmethod
    def cursor_visible(cls, t: float | None) -> bool:
        """At rest the cursor shows; animated it blinks."""
        return t is None or int(t * cls.BLINKS * 2) % 2 == 0


class AnalysisIcon(SideIcon):
    period_ms = 1800
    BARS = 3
    REST_HEIGHTS = (0.42, 0.7, 0.55)   # share of the chart's height, at rest

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.4, s * 0.075)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Axis: an L along the left and bottom.
        floor = rect.top() + s * 0.88
        axis = QPainterPath(QPointF(rect.left() + s * 0.08, rect.top() + s * 0.1))
        axis.lineTo(rect.left() + s * 0.08, floor)
        axis.lineTo(rect.right() - s * 0.04, floor)
        painter.setPen(QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(axis)

        # Bars: rising and falling in a wave; the one under the lens is coloured.
        lens_x = self.lens_x(t)
        chart_height = s * 0.66
        bar_width = s * 0.16
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(self.BARS):
            left = rect.left() + s * (0.2 + 0.24 * index)
            height = chart_height * self.bar_height(t, index)
            centre = (left - rect.left() + bar_width / 2) / s
            examined = t is not None and abs(centre - lens_x) < 0.13
            painter.setBrush(QColor(theme.LEAF if examined else theme.OCEAN))
            painter.drawRoundedRect(QRectF(left, floor - height - line_width / 2, bar_width, height),
                                    s * 0.03, s * 0.03)

        # Lens: a ring with a handle, sweeping over the bars.
        radius = s * 0.17
        centre = QPointF(rect.left() + s * lens_x, rect.top() + s * (0.34 + 0.04 * math.sin(2 * math.pi * (t or 0))))
        glass = QColor(_paper())
        glass.setAlpha(110)
        painter.setBrush(glass)
        painter.setPen(QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(centre, radius, radius)
        handle = QPointF(math.cos(math.radians(45)), math.sin(math.radians(45)))
        painter.drawLine(centre + handle * radius, centre + handle * (radius + s * 0.17))
        painter.restore()

    @classmethod
    def bar_height(cls, t: float | None, index: int) -> float:
        """Height of bar ``index`` at moment ``t``, as a share of the chart (a wave moving left to right)."""
        if t is None:
            return cls.REST_HEIGHTS[index]
        return 0.55 + 0.35 * math.sin(2 * math.pi * (t - index / cls.BARS))

    @staticmethod
    def lens_x(t: float | None) -> float:
        """The lens's centre across the icon (0-1): at rest over the right bar; animated, it sweeps there and back."""
        if t is None:
            return 0.7
        return 0.3 + 0.45 * (0.5 - 0.5 * math.cos(2 * math.pi * t))


class ExplainIcon(SideIcon):
    """A speech bubble with a sparkle (AI explanation); animated, the explanation's lines appear in
    the bubble one after another while the sparkle twinkles."""

    period_ms = 1800
    LINES = 3
    LINE_LENGTHS = (0.52, 0.42, 0.3)   # share of the icon's width

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.4, s * 0.075)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Bubble: a rounded box with a tail at the bottom left.
        left, top, right, bottom = rect.left() + s * 0.06, rect.top() + s * 0.2, rect.left() + s * 0.8, rect.top() + s * 0.74
        bubble = QPainterPath()
        bubble.addRoundedRect(QRectF(left, top, right - left, bottom - top), s * 0.12, s * 0.12)
        tail = QPainterPath(QPointF(left + s * 0.16, bottom - s * 0.02))
        tail.lineTo(left + s * 0.1, rect.top() + s * 0.92)
        tail.lineTo(left + s * 0.34, bottom - s * 0.02)
        bubble = bubble.united(tail)
        painter.setPen(QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bubble)

        # Lines of the explanation: written one after another.
        painter.setPen(QPen(QColor(theme.OCEAN), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for index in range(self.LINES):
            shown = self.line_shown(t, index)
            if shown <= 0:
                continue
            y = top + (bottom - top) * (0.3 + 0.2 * index)
            x0 = left + s * 0.12
            painter.drawLine(QPointF(x0, y), QPointF(x0 + s * self.LINE_LENGTHS[index] * shown, y))

        # Sparkle: a four-pointed star at the top right, twinkling.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.LEAF))
        painter.drawPath(self._star(QPointF(rect.left() + s * 0.82, rect.top() + s * 0.2), s * 0.2 * self.sparkle(t)))
        painter.restore()

    @classmethod
    def line_shown(cls, t: float | None, index: int) -> float:
        """How much of line ``index`` is written at moment ``t`` (0 to 1): all of them at rest."""
        if t is None:
            return 1.0
        start = index / (cls.LINES + 1)                 # each line in turn, then a pause with all shown
        return max(0.0, min(1.0, (t - start) * (cls.LINES + 1)))

    @staticmethod
    def sparkle(t: float | None) -> float:
        """The sparkle's size (share of its full size): twinkling between 0.55 and 1 while animated."""
        if t is None:
            return 1.0
        return 0.775 + 0.225 * math.cos(2 * math.pi * t * 2)

    @staticmethod
    def _star(centre: QPointF, radius: float) -> QPainterPath:
        inner = radius * 0.32
        star = QPainterPath()
        for point in range(8):
            angle = math.radians(point * 45 - 90)
            reach = radius if point % 2 == 0 else inner
            corner = QPointF(centre.x() + reach * math.cos(angle), centre.y() + reach * math.sin(angle))
            if point == 0:
                star.moveTo(corner)
            else:
                star.lineTo(corner)
        star.closeSubpath()
        return star


class VectorIcon(SideIcon):
    """A map polygon with its vertex nodes (vector maps / shapefiles); animated, the nodes
    light up one after another, as if the shape were being digitised."""

    period_ms = 2000
    # Vertices of a simple closed polygon, as shares of the icon (an arrow-like parcel outline).
    VERTICES = ((0.2, 0.32), (0.52, 0.16), (0.84, 0.4), (0.72, 0.82), (0.3, 0.74))

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.4, s * 0.075)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        corners = [QPointF(rect.left() + s * fx, rect.top() + s * fy) for fx, fy in self.VERTICES]
        shape = QPainterPath(corners[0])
        for corner in corners[1:]:
            shape.lineTo(corner)
        shape.closeSubpath()
        fill = QColor(theme.MINT)
        fill.setAlpha(120)
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(theme.OCEAN), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(shape)

        # Vertex nodes: square handles; the "active" one (lit in turn while animating) is green.
        active = None if t is None else int(t * len(corners)) % len(corners)
        node = s * 0.11
        painter.setPen(QPen(QColor(_ink()), line_width * 0.8))
        for index, corner in enumerate(corners):
            painter.setBrush(QColor(theme.LEAF if index == active else _paper()))
            painter.drawRect(QRectF(corner.x() - node / 2, corner.y() - node / 2, node, node))
        painter.restore()


class TerrainIcon(SideIcon):
    """A mountain range with a snow cap and a sun (the Digital Elevation Model); animated, the
    sun rises and the slope it lights up brightens, like a moving hillshade."""

    period_ms = 2600

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.4, s * 0.075)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        floor = rect.top() + s * 0.82

        # Sun: climbs across the top and back while animating.
        sweep = 0.75 if t is None else 0.2 + 0.6 * (0.5 - 0.5 * math.cos(2 * math.pi * t))
        sun = QPointF(rect.left() + s * sweep, rect.top() + s * (0.26 - 0.12 * math.sin(math.pi * sweep)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.LEAF))
        painter.drawEllipse(sun, s * 0.1, s * 0.1)

        # Back mountain.
        back = QPainterPath(QPointF(rect.left() + s * 0.06, floor))
        back.lineTo(rect.left() + s * 0.42, rect.top() + s * 0.34)
        back.lineTo(rect.left() + s * 0.72, floor)
        back.closeSubpath()
        lit = QColor(theme.MINT)
        lit.setAlpha(150)
        painter.setBrush(lit)
        painter.setPen(QPen(QColor(theme.OCEAN), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(back)

        # Front peak with a snow cap.
        apex = QPointF(rect.left() + s * 0.62, rect.top() + s * 0.2)
        front = QPainterPath(QPointF(rect.left() + s * 0.3, floor))
        front.lineTo(apex)
        front.lineTo(rect.right() - s * 0.04, floor)
        front.closeSubpath()
        painter.setBrush(QColor(theme.OCEAN))
        painter.drawPath(front)
        cap = QPainterPath(QPointF(apex.x() - s * 0.1, rect.top() + s * 0.33))
        cap.lineTo(apex)
        cap.lineTo(apex.x() + s * 0.1, rect.top() + s * 0.33)
        cap.lineTo(apex.x() + s * 0.03, rect.top() + s * 0.3)
        cap.lineTo(apex.x() - s * 0.02, rect.top() + s * 0.35)
        cap.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_paper()))
        painter.drawPath(cap)
        painter.restore()


class InterpolateIcon(SideIcon):
    """Sample points over an interpolated field (IDW); animated, rings spread out from each
    point like distance-weighted influence."""

    period_ms = 2200
    POINTS = ((0.3, 0.32), (0.7, 0.26), (0.5, 0.6), (0.24, 0.72), (0.76, 0.7))

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.2, s * 0.06)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        centres = [QPointF(rect.left() + s * fx, rect.top() + s * fy) for fx, fy in self.POINTS]
        grow = 0.0 if t is None else (t % 1.0)
        ring = QColor(theme.OCEAN)
        ring.setAlpha(110)
        painter.setPen(QPen(ring, line_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for centre in centres:  # expanding influence rings
            radius = s * (0.08 + 0.16 * grow)
            painter.drawEllipse(centre, radius, radius)

        painter.setPen(QPen(QColor(_ink()), line_width * 0.8))
        for index, centre in enumerate(centres):
            colour = QColor(theme.LEAF) if index == (0 if t is None else int(t * len(centres)) % len(centres)) \
                else QColor(theme.OCEAN)
            painter.setBrush(colour)
            painter.drawEllipse(centre, s * 0.06, s * 0.06)
        painter.restore()


class CatalogIcon(SideIcon):
    """A globe with a download arrow (fetching data from providers); animated, the arrow
    descends into a tray, as data lands on the computer."""

    period_ms = 1300

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.4, s * 0.075)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Globe (top).
        globe = QPointF(rect.left() + s * 0.5, rect.top() + s * 0.32)
        radius = s * 0.22
        painter.setPen(QPen(QColor(theme.OCEAN), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(globe, radius, radius)
        painter.drawLine(QPointF(globe.x() - radius, globe.y()), QPointF(globe.x() + radius, globe.y()))
        meridian = QRectF(globe.x() - radius * 0.5, globe.y() - radius, radius, radius * 2)
        painter.drawArc(meridian, 90 * 16, 180 * 16)
        painter.drawArc(meridian, -90 * 16, 180 * 16)

        # Tray at the bottom.
        tray_top, bottom = rect.top() + s * 0.74, rect.top() + s * 0.9
        tray = QPainterPath(QPointF(rect.left() + s * 0.2, tray_top))
        tray.lineTo(rect.left() + s * 0.2, bottom)
        tray.lineTo(rect.right() - s * 0.2, bottom)
        tray.lineTo(rect.right() - s * 0.2, tray_top)
        painter.setPen(QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(tray)

        # Download arrow between globe and tray.
        lane = QRectF(rect.left(), globe.y() + radius * 0.4, s, s * 0.28)
        offset = (t or 0.0) * lane.height()
        painter.setClipRect(lane)
        painter.setPen(QPen(QColor(theme.LEAF), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        x = globe.x()
        for shift in (offset, offset - lane.height()):
            top = lane.top() + shift
            tip = top + s * 0.14
            painter.drawLine(QPointF(x, top), QPointF(x, tip))
            head = QPainterPath(QPointF(x - s * 0.08, tip - s * 0.08))
            head.lineTo(x, tip)
            head.lineTo(x + s * 0.08, tip - s * 0.08)
            painter.drawPath(head)
        painter.restore()


class PredictIcon(SideIcon):
    """Machine-learning prediction: past values as dots on a rising line, then a dashed forecast
    fanning out into an uncertainty cone; animated, the forecast grows out of the present and a
    network node at its tip pulses."""

    period_ms = 2000
    PAST = ((0.12, 0.72), (0.27, 0.62), (0.42, 0.66), (0.55, 0.5))   # oldest to the present

    def paint(self, painter: QPainter, rect: QRectF, t: float | None) -> None:
        s = rect.width()
        line_width = max(1.3, s * 0.07)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        points = [QPointF(rect.left() + s * fx, rect.top() + s * fy) for fx, fy in self.PAST]

        # the past: a solid line through the dated values
        painter.setPen(QPen(QColor(_ink()), line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        painter.drawPath(path)

        # the forecast: a cone of uncertainty and a dashed line, growing out of the present
        grow = self.forecast_reach(t)
        present = points[-1]
        tip = QPointF(present.x() + s * 0.33 * grow, present.y() - s * 0.3 * grow)
        cone = QPainterPath(present)
        cone.lineTo(tip.x(), tip.y() - s * 0.14 * grow)
        cone.lineTo(tip.x(), tip.y() + s * 0.14 * grow)
        cone.closeSubpath()
        shade = QColor(theme.OCEAN)
        shade.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawPath(cone)
        dashed = QPen(QColor(theme.LEAF), line_width, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
        dashed.setDashPattern([1.6, 1.6])
        painter.setPen(dashed)
        painter.drawLine(present, tip)

        # dots on the past values; a pulsing node (a neuron) at the forecast's tip
        painter.setPen(QPen(QColor(_ink()), line_width * 0.7))
        painter.setBrush(QColor(_paper()))
        for point in points:
            painter.drawEllipse(point, s * 0.06, s * 0.06)
        pulse = 1.0 if t is None else 0.8 + 0.35 * abs(math.sin(math.pi * 2 * t))
        painter.setBrush(QColor(theme.LEAF))
        painter.setPen(QPen(QColor(_ink()), line_width * 0.7))
        painter.drawEllipse(tip, s * 0.08 * pulse, s * 0.08 * pulse)
        painter.restore()

    @staticmethod
    def forecast_reach(t: float | None) -> float:
        """How far the forecast reaches at moment ``t`` (0.3 to 1); at rest, all the way."""
        if t is None:
            return 1.0
        return 0.3 + 0.7 * min(1.0, (t % 1.0) / 0.75)
