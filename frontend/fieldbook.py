"""Layout 3's visual world: the surveyor's field book.

Every page is a ruled, indexed spread under a graphite cover with a yellow spine. The world
lends four things and only these: palette, type, density, and one signature move (each page's
index number is its real keyboard shortcut, set in the book's yellow beside its name).

All values follow the active theme, and ``overlay()`` / ``grid_tile()`` are rebuilt on a live
theme change, so the book reads in light, dark blue-green and dark grey alike — dark first.
"""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from PyQt6.QtGui import QColor, QImage

from frontend import accent, fonts, layout_mode, palette, theme

FIELD_YELLOW = "#E8B923"   # the field book's yellow, in the three original themes
# The themes built from three colours keep their third colour for buttons, animation and effects, so
# there the spine, rules and entry numbers take that accent instead of the book's yellow.
THREE_COLOUR_THEMES = palette.THREE_COLOUR_THEMES
SPINE = FIELD_YELLOW       # the spine and its rules; set by refresh() for the active theme
MONO = fonts.MONO          # one measurement face for every figure: bundled JetBrains Mono
MONO_STACK = f'"{MONO}", "Consolas"'
CARD_RADIUS = 6            # pages are cut square-ish; buttons keep the app's 10px
CHROME_HEIGHT = 160        # the division strip and the open run log, above and below every page

# One hue per division of the book, so the reader always knows which part they are in.
# Dark themes take the light tints; the light theme takes the ink-dark ones (text-safe on white).
_DIVISIONS = {
    "work":    ("#5DA9E9", "#1F6FB2"),
    "analyse": ("#6FCF97", "#23845E"),
    "explain": ("#B39DDB", "#6B4FA8"),
    "report":  ("#F2994A", "#A8530F"),
}


DIVISION_NAMES = tuple(_DIVISIONS)


def _three_colour() -> bool:
    return palette.THEME in THREE_COLOUR_THEMES


def refresh() -> None:
    """Pick the spine colour for the active theme (at import and on a live theme change)."""
    global SPINE
    SPINE = palette.ACTIVE["BUTTON"] if _three_colour() else FIELD_YELLOW


def division_on_cover(name: str) -> str:
    """A division's hue on the cover, which is dark in every theme. The three-colour themes name
    divisions in their text colour, not in four extra hues."""
    return cover_muted() if _three_colour() else _DIVISIONS[name][0]


@lru_cache(maxsize=1)
def active() -> bool:
    """Layout 3 is on. Read once: changing the layout restarts the app."""
    return layout_mode.is_studio()


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    ).name()


def cover() -> str:
    """The cover: darker than every page in a dark theme, graphite over a light one. A light
    three-colour theme binds its book in its second colour (its text colour)."""
    if palette.IS_DARK:
        return _mix(palette.ACTIVE["PAGE_BG"], "#000000", 0.38)
    return palette.ACTIVE["INK"] if _three_colour() else "#24282B"


def cover_raised() -> str:
    return _mix(cover(), cover_text(), 0.10)


def cover_text() -> str:
    # On a light three-colour theme the cover is its dark text colour, so its words take the ground.
    return palette.ACTIVE["PAGE_BG"] if (_three_colour() and not palette.IS_DARK) else "#D3D7DA"


def cover_muted() -> str:
    return _mix(cover_text(), cover(), 0.30) if _three_colour() else "#A3AAB0"


def yellow_ink() -> str:
    """The spine's colour where it is text: darkened on a light page so it stays legible. The
    three-colour themes use their accent's text-safe shade (LEAF)."""
    if _three_colour():
        return palette.ACTIVE["LEAF"]
    return "#8A6400" if not palette.IS_DARK else SPINE


def index_ink() -> str:
    """The side index's digits on the cover. A light three-colour theme binds its cover in its dark
    text colour, where the plain accent would read at ~3:1, so the digits lift toward the cover's text."""
    if _three_colour() and not palette.IS_DARK:
        return _mix(SPINE, cover_text(), 0.45)
    return SPINE


def rule() -> str:
    return theme.BORDER


def grid_line() -> str:
    return _mix(palette.ACTIVE["PAGE_BG"], theme.BORDER, 0.55)


def division(name: str) -> str:
    if _three_colour():
        return palette.ACTIVE["BUTTON"]  # division tabs are buttons: they take the accent
    dark, light = _DIVISIONS[name]
    return dark if palette.IS_DARK else light


def grid_tile() -> str:
    """An 8x8 tile of the book's ruling (one hairline right and bottom), written for QSS to repeat."""
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(QColor(palette.ACTIVE["PAGE_BG"]))
    line = QColor(grid_line())
    for i in range(8):
        image.setPixelColor(7, i, line)
        image.setPixelColor(i, 7, line)
    folder = Path(tempfile.gettempdir()) / "gee-assist-fieldbook"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"grid-{palette.THEME}.png"
    image.save(str(path))
    return path.as_posix()


def overlay() -> str:
    """The field book's rules for any page: appended to every page's own stylesheet in Layout 3.

    Kept to the world's four contributions (palette, type, density, the ruled module). It never
    moves controls or changes what a page does.
    """
    ink, rule_, muted, white = theme.INK, rule(), theme.MUTED, theme.WHITE
    return f"""
/* ---- field book (Layout 3) ---- */
QLabel#PageTitle {{ font-family: "{theme.SERIF}"; font-size: 20pt; font-weight: 600; color: {ink}; }}
QLabel#PageSubtitle {{ color: {muted}; font-size: 10pt; }}
QLabel#SectionTitle, QLabel#StepTitle, QLabel#CardTitle {{
    font-family: "{theme.SERIF}"; font-size: 12.5pt; font-weight: 600; color: {ink};
    padding-bottom: 4px; border-bottom: 1px solid {SPINE};
}}
QLabel#Overline, QLabel#PageEyebrow {{ max-height: 0px; font-size: 1px; color: transparent; margin: 0; padding: 0; }}
QFrame#DashboardPanel, QFrame#StatsCard, QFrame#DownloadSection, QFrame#ResultCard,
QFrame#AnalysisPanel, QFrame#ExplanationCard, QFrame#SectionCard, QFrame#SideCard, QFrame#ReportCard,
QFrame#CatalogCard, QFrame#ViewerPanel {{
    background: {white}; border: 1px solid {rule_}; border-radius: {CARD_RADIUS}px;
}}
QLabel#GlanceValue, QLabel#StatValue {{
    font-family: {MONO_STACK}; font-size: 17pt; color: {ink};
}}
QLabel#ItemPath, QLabel#JobEta, QLabel#JobSize, QLabel#StatValue, QLabel#ChunkSetting {{
    font-family: {MONO_STACK}; font-size: 9pt;
}}
QHeaderView::section {{
    background: transparent; color: {muted}; font-weight: 600; font-size: 9pt;
    border: none; border-bottom: 1px solid {SPINE}; padding: 6px 8px;
}}
QTableWidget, QTableView {{ gridline-color: {rule_}; }}
QProgressBar#JobProgress::chunk, QProgressBar#BusyBar::chunk {{ background: {SPINE}; }}
QFrame#GlanceTile {{
    background: transparent; border: none; border-right: 1px solid {rule_}; border-radius: 0;
}}
QFrame#RecentProject {{
    background: transparent; border: none; border-bottom: 1px solid {rule_}; border-radius: 0;
}}
QFrame#RecentProject[current="true"] {{ border-bottom: 1px solid {SPINE}; }}
QLabel#EntryNumber {{ font-family: {MONO_STACK}; font-size: 10pt; font-weight: 600; color: {yellow_ink()}; }}
QLabel#ItemPath {{ color: {muted}; }}
QPushButton#PrimaryButton, QPushButton#SecondaryButton, QPushButton#DangerButton {{
    border-radius: {accent.BUTTON_RADIUS}px;
}}
QFrame#SectionHeader {{
    background: transparent; border: none; border-bottom: 1px solid {SPINE}; border-radius: 0;
}}
QFrame#FieldSpread {{ background: {white}; border: 1px solid {rule_}; border-radius: {CARD_RADIUS}px; }}
QFrame#FieldSpread QFrame#DashboardPanel {{ background: transparent; border: none; }}
QTableWidget#FieldTable {{ background: transparent; border: none; color: {theme.TEXT}; }}
QTableWidget#FieldTable::item {{ padding: 4px 6px; border: none; border-bottom: 1px solid {rule_}; }}
QWidget#FieldRightPage {{ background: transparent; border: none; border-left: 1px solid {SPINE}; }}
"""


def division_strip_css() -> str:
    """The division tabs at the top of every page (Work, Analyse, Explain, Report)."""
    on_hue = (palette.ACTIVE["PRIMARY_TEXT"] if _three_colour()
              else "#0F1416" if palette.IS_DARK else "#FFFFFF")
    rules = [
        f"QFrame#DivisionStrip {{ background: transparent; border: none; border-bottom: 1px solid {rule()}; }}",
        f"QPushButton#DivisionTab {{ background: transparent; color: {theme.MUTED}; border: 1px solid {rule()}; "
        f"border-radius: {accent.BUTTON_RADIUS}px; padding: 5px 14px; font-weight: 600; }}",
        f"QPushButton#DivisionTab:hover {{ color: {theme.INK}; border-color: {theme.BORDER_HOVER}; }}",
    ]
    for name in DIVISION_NAMES:
        hue = division(name)
        rules.append(f'QPushButton#DivisionTab[division="{name}"]:checked {{ background: {hue}; '
                     f"border-color: {hue}; color: {on_hue}; }}")
    return "\n".join(rules)


refresh()
