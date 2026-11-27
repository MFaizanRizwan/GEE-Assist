"""The terminal's colours and font, from the app's theme.

Every text style (``text.TEXT``, ``text.ERROR``...) gets a colour of the active palette,
so the terminal follows the light and dark themes like the rest of the app. In the
dark themes the output area uses the darker field colour, as a terminal usually does.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QTextCharFormat

from frontend import palette
from frontend.gkonsol import text

# Amber for warnings: readable on each theme's terminal background.
WARNING = {"light": "#9A6700", "dark-green": "#F2C46D", "dark-grey": "#F0C674"}
FONT_FAMILIES = ("IBM Plex Mono", "JetBrains Mono", "Cascadia Mono", "Cascadia Code", "Consolas", "Courier New")  # first: bundled
FONT_POINT_SIZE = 10


def _colour(name: str) -> str:
    return palette.ACTIVE[name]


def _muted() -> str:
    """Muted terminal text. The light theme's MUTED is ~3.9:1 on the white log, under WCAG AA for
    body text, so there it is drawn 35% of the way toward the theme's ink (~5.7:1)."""
    if palette.IS_DARK:
        return _colour("MUTED")
    muted, ink = QColor(_colour("MUTED")), QColor(_colour("INK"))
    mix = [round(a + (b - a) * 0.35) for a, b in ((muted.red(), ink.red()), (muted.green(), ink.green()),
                                                 (muted.blue(), ink.blue()))]
    return QColor(*mix).name()


BACKGROUND = HEADER = BORDER = SELECTION = ""
# style -> (colour, bold); filled by refresh()
STYLE_COLOURS: dict[str, tuple[str, bool]] = {}


def refresh() -> None:
    """Recompute the terminal's colours from the active palette (at import and on a live theme change)."""
    global BACKGROUND, HEADER, BORDER, SELECTION
    BACKGROUND = _colour("FIELD_BG") if palette.IS_DARK else _colour("WHITE")
    HEADER = _colour("WHITE") if palette.IS_DARK else _colour("FOAM")
    BORDER = _colour("BORDER")
    SELECTION = _colour("OCEAN")
    STYLE_COLOURS.clear()
    STYLE_COLOURS.update(_style_colours())


def _style_colours() -> dict[str, tuple[str, bool]]:
    from frontend import fieldbook  # late: fieldbook imports theme

    prompt = fieldbook.yellow_ink() if fieldbook.active() else _colour("LEAF")  # Layout 3: the book's yellow
    return {
    text.TEXT: (_colour("TEXT"), False),
    text.MUTED: (_muted(), False),
    text.BOLD: (_colour("INK"), True),
    text.ACCENT: (_colour("LEAF"), False),
    text.INFO: (_colour("OCEAN"), False),
    text.SUCCESS: (_colour("SUCCESS"), False),
    text.WARNING: (WARNING.get(palette.THEME, WARNING["dark-green" if palette.IS_DARK else "light"]), False),
    text.ERROR: (_colour("ERROR"), False),
    text.HEADING: (_colour("INK"), True),
    text.COMMAND: (_colour("INK"), True),
    text.PROMPT_USER: (prompt, True),
    text.PROMPT_PATH: (_colour("OCEAN"), True),
    }


refresh()


def char_formats() -> dict[str, QTextCharFormat]:
    """A text format for every style."""
    formats = {}
    for style, (colour, bold) in STYLE_COLOURS.items():
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colour))
        fmt.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        formats[style] = fmt
    return formats


def monospace_font() -> QFont:
    """The first installed font of ``FONT_FAMILIES``, else the system's fixed-width font."""
    installed = set(QFontDatabase.families())
    for family in FONT_FAMILIES:
        if family in installed:
            font = QFont(family, FONT_POINT_SIZE)
            break
    else:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(FONT_POINT_SIZE)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font
