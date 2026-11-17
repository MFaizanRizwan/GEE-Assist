"""Vertical navigation bar on the left of the signed-in window.

The bar slides between two widths (``set_expanded``). Expanded, its buttons show their
full names ("Downloads"); collapsed, only a short label ("D"). It opens by itself while the
pointer is over it and closes again shortly after the pointer leaves (not while one of its
menus, e.g. the account menu, is open). ``set_pinned(True)`` keeps it open. It starts
collapsed unless created with ``expanded=True``, which also pins it. The logo at the top is the way home: clicking it emits
``home_requested`` (the signed-in window shows the dashboard).
Any widget added with a ``set_compact(bool)`` method follows the same switch.

Sliding open, the names appear first and are uncovered as the bar widens; sliding
closed, they are covered first and switch to the short labels at the end.

The slide is driven by a plain timer and a clock rather than a Qt animation: Qt
WebEngine (used by the sign-in screen and the map) can leave Qt's animation timing
stopped after its window closes, which would freeze the bar half-way.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QElapsedTimer, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QApplication,
    QBoxLayout,
    QFrame,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend import theme
from frontend.widgets.side_icons import SideIcon

LOGO_SIZE = 64
SIDE_MARGIN = 6
BORDER = 1        # the line on the bar's right edge
COLLAPSED_WIDTH = LOGO_SIZE + 2 * SIDE_MARGIN + BORDER   # just wide enough for the logo
EXPANDED_WIDTH = 220
SLIDE_MS = 220
FRAME_MS = 15     # about 60 frames a second
HOVER_OPEN_MS = 150   # the pointer rests on the bar this long before it opens (passing over does not)
HOVER_CLOSE_MS = 350  # and is away this long before it closes
BUTTON_HEIGHT = 40  # collapsed, a button is as wide as it is high: a circle
ICON_SIZE = 22
ICON_LEFT = 14      # expanded: the icon's distance from the button's left edge

STYLESHEET = f"""
#SideBar {{ background: {theme.WHITE}; border: none; border-right: {BORDER}px solid {theme.BORDER}; }}
QToolButton#SideLogo {{ border: none; background: transparent; padding: 0; }}
QPushButton#SideButton {{
    border: none; border-radius: 8px; background: transparent; color: {theme.INK};
    font-weight: 600; text-align: left; padding: 0 14px;
}}
QPushButton#SideButton[hasIcon="true"] {{ padding-left: {ICON_LEFT + ICON_SIZE + 10}px; }}
QPushButton#SideButton[compact="true"] {{ text-align: center; padding: 0; border-radius: {BUTTON_HEIGHT // 2}px; }}
QPushButton#SideButton:hover {{ background: {theme.FOAM}; }}
QPushButton#SideButton:pressed, QPushButton#SideButton:checked {{ background: {theme.MINT}; }}
"""


class SideButton(QPushButton):
    """A navigation button: its full name when the bar is expanded, a short label when collapsed.

    With an ``icon``, the icon stands before the name, and collapsed it replaces the
    short label. The icon is animated only while the pointer is over the button.
    """

    def __init__(self, text: str, short: str, icon: SideIcon | None = None, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.full_text, self.short_text = text, short
        self.icon_drawing = icon
        self._compact = False
        self._frames = QTimer(self)  # repaints while hovered; a plain timer, like the slide
        self._frames.setInterval(FRAME_MS)
        self._frames.timeout.connect(self.update)
        self._clock = QElapsedTimer()
        self.setProperty("hasIcon", icon is not None)  # not "icon": buttons have that already
        self.setObjectName("SideButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        self.setFixedHeight(BUTTON_HEIGHT)
        # Narrower than its text while the bar slides: the text is clipped, not the bar held open.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        short = "" if self.icon_drawing else self.short_text  # the icon is enough when collapsed
        self.setText(short if compact else self.full_text)
        if compact:
            self.setFixedWidth(BUTTON_HEIGHT)
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(QWIDGETSIZE_MAX)
        self.setProperty("compact", compact)
        self.style().unpolish(self)
        self.style().polish(self)

    # ------------------------------------------------------------- icon animation
    def is_animating(self) -> bool:
        return self._frames.isActive()

    def animation_moment(self) -> float | None:
        """Where the icon's animation is (0 to 1), or None when it is at rest."""
        if not self.is_animating() or self.icon_drawing is None:
            return None
        return (self._clock.elapsed() % self.icon_drawing.period_ms) / self.icon_drawing.period_ms

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().enterEvent(event)
        if self.icon_drawing is not None:
            self._clock.start()
            self._frames.start()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().leaveEvent(event)
        self._stop_animation()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().hideEvent(event)
        self._stop_animation()  # hidden while hovered: no leave event comes

    def _stop_animation(self) -> None:
        if self._frames.isActive():
            self._frames.stop()
            self.update()  # back to the icon at rest

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)
        if self.icon_drawing is None:
            return
        left = (self.width() - ICON_SIZE) / 2 if self._compact else ICON_LEFT
        area = QRectF(left, (self.height() - ICON_SIZE) / 2, ICON_SIZE, ICON_SIZE)
        painter = QPainter(self)
        self.icon_drawing.paint(painter, area, self.animation_moment())
        painter.end()


class SideBar(QFrame):
    expanded_changed = pyqtSignal(bool)
    pinned_changed = pyqtSignal(bool)
    home_requested = pyqtSignal()  # the logo was clicked

    def __init__(self, logo: QPixmap, parent: QWidget | None = None, expanded: bool = False):
        super().__init__(parent)
        self.setObjectName("SideBar")
        self.setStyleSheet(STYLESHEET)
        self._expanded = expanded
        self._pinned = expanded       # kept open whatever the pointer does
        self._hovered = False
        self._compact_widgets: list[QWidget] = []
        self._layout_of: dict[QWidget, QBoxLayout] = {}

        self.logo = QToolButton(objectName="SideLogo")
        self.logo.setIcon(QIcon(logo))
        self.logo.setIconSize(QSize(LOGO_SIZE, LOGO_SIZE))
        self.logo.setFixedSize(LOGO_SIZE, LOGO_SIZE)  # exactly the icon, so the circles line up under it
        self.logo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logo.setToolTip("Dashboard")
        self.logo.clicked.connect(self.home_requested)

        self._items = QVBoxLayout()
        self._items.setSpacing(4)
        self._footer = QVBoxLayout()
        self._footer.setSpacing(6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SIDE_MARGIN, 18, SIDE_MARGIN, 18)
        layout.setSpacing(18)
        layout.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignLeft)  # stays put while the bar slides
        layout.addLayout(self._items)
        layout.addStretch(1)
        layout.addLayout(self._footer)

        width = EXPANDED_WIDTH if expanded else COLLAPSED_WIDTH
        self.setFixedWidth(width)
        self._slide = QTimer(self)
        self._slide.setInterval(FRAME_MS)
        self._slide.timeout.connect(self._slide_step)
        self._slide_clock = QElapsedTimer()
        self._slide_from = self._slide_to = width
        self._easing = QEasingCurve(QEasingCurve.Type.OutCubic)

        self._hover_open = QTimer(self)
        self._hover_open.setSingleShot(True)
        self._hover_open.setInterval(HOVER_OPEN_MS)
        self._hover_open.timeout.connect(self._open_on_hover)
        self._hover_close = QTimer(self)
        self._hover_close.setSingleShot(True)
        self._hover_close.setInterval(HOVER_CLOSE_MS)
        self._hover_close.timeout.connect(self._close_after_hover)

    # ------------------------------------------------------------- contents
    def add_button(self, text: str, short: str, footer: bool = False, icon: SideIcon | None = None) -> SideButton:
        button = SideButton(text, short, icon)
        self.add_widget(button, footer)
        return button

    def add_widget(self, widget: QWidget, footer: bool = False) -> None:
        """Add ``widget`` under the logo, or at the bottom of the bar with ``footer``."""
        layout = self._footer if footer else self._items
        layout.addWidget(widget)
        self._layout_of[widget] = layout
        if hasattr(widget, "set_compact"):
            self._compact_widgets.append(widget)
            self._apply_compact(widget, not self._expanded)

    # ------------------------------------------------------------- sliding
    def is_expanded(self) -> bool:
        return self._expanded

    def is_sliding(self) -> bool:
        return self._slide.isActive()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    # ------------------------------------------------------------- hover and pinning
    def is_pinned(self) -> bool:
        return self._pinned

    def is_hovered(self) -> bool:
        return self._hovered

    def set_pinned(self, pinned: bool) -> None:
        """Keep the bar open (View → Side bar), or let it follow the pointer again."""
        if pinned == self._pinned:
            return
        self._pinned = pinned
        self._hover_close.stop()
        if pinned:
            self.set_expanded(True)
        elif not self._hovered:
            self.set_expanded(False)
        self.pinned_changed.emit(pinned)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().enterEvent(event)
        self._hovered = True
        self._hover_close.stop()
        if not self._expanded:
            self._hover_open.start()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().leaveEvent(event)  # moving onto one of the bar's own buttons is not leaving it
        self._hovered = False
        self._hover_open.stop()
        if self._expanded and not self._pinned:
            self._hover_close.start()

    def _open_on_hover(self) -> None:
        if self._hovered:
            self.set_expanded(True)

    def _close_after_hover(self) -> None:
        if self._pinned or self._hovered:
            return
        if QApplication.activePopupWidget() is not None:  # e.g. the account menu opened from the bar
            self._hover_close.start()  # look again once it is closed
            return
        self.set_expanded(False)

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._slide.stop()
        target = EXPANDED_WIDTH if expanded else COLLAPSED_WIDTH
        if expanded:
            self._set_compact(False)  # the names are uncovered as the bar widens
        if animate and self.isVisible():
            self._slide_from, self._slide_to = self.width(), target
            self._slide_clock.start()
            self._slide.start()
        else:
            self.setFixedWidth(target)
            self._slide_finished()
        self.expanded_changed.emit(expanded)

    def _slide_step(self) -> None:
        progress = min(1.0, self._slide_clock.elapsed() / SLIDE_MS)
        eased = self._easing.valueForProgress(progress)
        self.setFixedWidth(round(self._slide_from + (self._slide_to - self._slide_from) * eased))
        if progress >= 1.0:
            self._slide.stop()
            self._slide_finished()

    def _slide_finished(self) -> None:
        if not self._expanded:
            self._set_compact(True)  # short labels once the bar is narrow

    def _set_compact(self, compact: bool) -> None:
        for widget in self._compact_widgets:
            self._apply_compact(widget, compact)

    def _apply_compact(self, widget: QWidget, compact: bool) -> None:
        widget.set_compact(compact)
        if isinstance(widget, SideButton):  # the circle sits under the logo; full names fill the row
            centre = Qt.AlignmentFlag.AlignHCenter if compact else Qt.AlignmentFlag(0)
            self._layout_of[widget].setAlignment(widget, centre)

