"""GEE-Assist light classical theme: white surfaces, earth greens and sky blues, serif headings."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication

from frontend import accent, fonts, palette

# Bundled families: Space Grotesk for headings/warnings, Inter for body. The names
# keep the historic SERIF/SANS spellings so the many call sites need no change.
# Fonts do not change with the theme, so they stay as plain constants.
SERIF = fonts.DISPLAY
SANS = fonts.BODY
WARNING = fonts.WARNING

_ICONS_DIR = Path(__file__).resolve().parent / "resources" / "icons"
CHECK_ICON = (_ICONS_DIR / "check.svg").as_posix()

# Every theme-dependent name below is (re)assigned by refresh(), so a live theme change
# (palette.set_theme + refresh + re-apply) recolours the whole app without a restart.
WHITE = INK = TEXT = MUTED = SUBTLE = BORDER = BORDER_STRONG = FIELD_BG = ""
LEAF = LEAF_DARK = OCEAN = OCEAN_DARK = MINT = SKY = FOAM = ""
ERROR = ERROR_BG = SUCCESS = SUCCESS_BG = INFO_BG = ERROR_BORDER = SUCCESS_BORDER = INFO_BORDER = ERROR_FIELD_BG = ""
BORDER_HOVER = DISABLED_BG = PRIMARY_TEXT = PRIMARY_DISABLED_TEXT = PRIMARY_DISABLED_FROM = PRIMARY_DISABLED_TO = ""
OPEN_BUTTON_TOP = PAGE_GRADIENT_TOP = PAGE_GRADIENT_MIDDLE = PAGE_GRADIENT_BOTTOM = ""
HERO_TOP = HERO_MIDDLE = HERO_BOTTOM = TILE_DISABLED_BG = PROGRESS_TRACK = PROGRESS_PAUSED = PROGRESS_FAILED = ""
TABLE_LINE = CHART_GRID = SHADOW = SPLASH_BG = ""
ACCENT_SOLID = ACCENT_SOLID_HOVER = ACCENT_FROM = ACCENT_TO = ACCENT_FROM_HOVER = ACCENT_TO_HOVER = ACCENT_TEXT = ACCENT_SOFT = ""
STYLESHEET = MENU_STYLE = ""


def color(hex_value: str, alpha: int = 255) -> QColor:
    c = QColor(hex_value)
    c.setAlpha(alpha)
    return c


def heading_font(point_size: int, bold: bool = False) -> QFont:
    font = QFont(SERIF, point_size)
    font.setBold(bold)
    return font


def refresh() -> None:
    """Recompute every colour constant and rebuild the stylesheets from the active palette."""
    global WHITE, INK, TEXT, MUTED, SUBTLE, BORDER, BORDER_STRONG, FIELD_BG
    global LEAF, LEAF_DARK, OCEAN, OCEAN_DARK, MINT, SKY, FOAM
    global ERROR, ERROR_BG, SUCCESS, SUCCESS_BG, INFO_BG, ERROR_BORDER, SUCCESS_BORDER, INFO_BORDER, ERROR_FIELD_BG
    global BORDER_HOVER, DISABLED_BG, PRIMARY_TEXT, PRIMARY_DISABLED_TEXT, PRIMARY_DISABLED_FROM, PRIMARY_DISABLED_TO
    global OPEN_BUTTON_TOP, PAGE_GRADIENT_TOP, PAGE_GRADIENT_MIDDLE, PAGE_GRADIENT_BOTTOM
    global HERO_TOP, HERO_MIDDLE, HERO_BOTTOM, TILE_DISABLED_BG, PROGRESS_TRACK, PROGRESS_PAUSED, PROGRESS_FAILED
    global TABLE_LINE, CHART_GRID, SHADOW, SPLASH_BG
    global ACCENT_SOLID, ACCENT_SOLID_HOVER, ACCENT_FROM, ACCENT_TO, ACCENT_FROM_HOVER, ACCENT_TO_HOVER, ACCENT_TEXT, ACCENT_SOFT
    global STYLESHEET, MENU_STYLE

    accent.refresh()
    _P = palette.ACTIVE
    WHITE = _P["WHITE"]; INK = _P["INK"]; TEXT = _P["TEXT"]; MUTED = _P["MUTED"]; SUBTLE = _P["SUBTLE"]
    BORDER = _P["BORDER"]; BORDER_STRONG = _P["BORDER_STRONG"]; FIELD_BG = _P["FIELD_BG"]
    LEAF = _P["LEAF"]; LEAF_DARK = _P["LEAF_DARK"]; OCEAN = _P["OCEAN"]; OCEAN_DARK = _P["OCEAN_DARK"]
    MINT = _P["MINT"]; SKY = _P["SKY"]; FOAM = _P["FOAM"]
    ERROR = _P["ERROR"]; ERROR_BG = _P["ERROR_BG"]; SUCCESS = _P["SUCCESS"]; SUCCESS_BG = _P["SUCCESS_BG"]
    INFO_BG = _P["INFO_BG"]; ERROR_BORDER = _P["ERROR_BORDER"]; SUCCESS_BORDER = _P["SUCCESS_BORDER"]
    INFO_BORDER = _P["INFO_BORDER"]; ERROR_FIELD_BG = _P["ERROR_FIELD_BG"]
    BORDER_HOVER = _P["BORDER_HOVER"]; DISABLED_BG = _P["DISABLED_BG"]; PRIMARY_TEXT = _P["PRIMARY_TEXT"]
    PRIMARY_DISABLED_TEXT = _P["PRIMARY_DISABLED_TEXT"]; PRIMARY_DISABLED_FROM = _P["PRIMARY_DISABLED_FROM"]
    PRIMARY_DISABLED_TO = _P["PRIMARY_DISABLED_TO"]; OPEN_BUTTON_TOP = _P["OPEN_BUTTON_TOP"]
    PAGE_GRADIENT_TOP = _P["PAGE_GRADIENT_TOP"]; PAGE_GRADIENT_MIDDLE = _P["PAGE_GRADIENT_MIDDLE"]
    PAGE_GRADIENT_BOTTOM = _P["PAGE_GRADIENT_BOTTOM"]; HERO_TOP = _P["HERO_TOP"]; HERO_MIDDLE = _P["HERO_MIDDLE"]
    HERO_BOTTOM = _P["HERO_BOTTOM"]; TILE_DISABLED_BG = _P["TILE_DISABLED_BG"]; PROGRESS_TRACK = _P["PROGRESS_TRACK"]
    PROGRESS_PAUSED = _P["PROGRESS_PAUSED"]; PROGRESS_FAILED = _P["PROGRESS_FAILED"]; TABLE_LINE = _P["TABLE_LINE"]
    CHART_GRID = _P["CHART_GRID"]; SHADOW = _P["SHADOW"]; SPLASH_BG = _P["SPLASH_BG"]
    ACCENT_SOLID = accent.SOLID; ACCENT_SOLID_HOVER = accent.SOLID_HOVER
    ACCENT_FROM = accent.FROM; ACCENT_TO = accent.TO
    ACCENT_FROM_HOVER = accent.FROM_HOVER; ACCENT_TO_HOVER = accent.TO_HOVER
    ACCENT_TEXT = accent.TEXT; ACCENT_SOFT = accent.SOFT

    rad = accent.BUTTON_RADIUS  # one radius for every button
    STYLESHEET = f"""
QWidget {{
    font-family: "{SANS}";
    font-size: 10pt;
    color: {TEXT};
}}
QToolTip {{
    background: {WHITE}; color: {INK}; border: 1px solid {BORDER}; padding: 4px 6px;
}}

/* ---- text ---- */
QLabel#Title {{ font-family: "{SERIF}"; font-size: 23pt; color: {INK}; }}
QLabel#Subtitle {{ color: {MUTED}; font-size: 10.5pt; }}
QLabel#FieldLabel {{ color: {INK}; font-weight: 600; font-size: 9.5pt; }}
QLabel#FieldError {{ color: {ERROR}; font-family: "{WARNING}"; font-size: 8.5pt; }}
QLabel#FieldHint {{ color: {SUBTLE}; font-size: 8.5pt; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Divider {{ color: {SUBTLE}; font-size: 9pt; }}

/* ---- banners ---- */
QLabel#ErrorBanner, QLabel#SuccessBanner, QLabel#InfoBanner {{
    border-radius: 8px; padding: 9px 12px; font-size: 9.5pt;
    font-family: "{WARNING}"; font-weight: 600;
}}
QLabel#ErrorBanner {{ background: {ERROR_BG}; color: {ERROR}; border: 1px solid {ERROR_BORDER}; }}
QLabel#SuccessBanner {{ background: {SUCCESS_BG}; color: {SUCCESS}; border: 1px solid {SUCCESS_BORDER}; }}
QLabel#InfoBanner {{ background: {INFO_BG}; color: {OCEAN_DARK}; border: 1px solid {INFO_BORDER}; }}

/* ---- card ---- */
QFrame#AuthCard {{
    background: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 18px;
}}

/* ---- inputs ---- */
QLineEdit {{
    background: {FIELD_BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: 9px;
    padding: 9px 12px;
    font-size: 10.5pt;
    color: {INK};
    selection-background-color: {OCEAN};
}}
QLineEdit:hover {{ border-color: {BORDER_HOVER}; }}
QLineEdit:focus {{ border: 1.5px solid {LEAF}; background: {WHITE}; }}
QLineEdit[invalid="true"] {{ border: 1.5px solid {ERROR}; background: {ERROR_FIELD_BG}; }}
QLineEdit:disabled {{ color: {SUBTLE}; background: {DISABLED_BG}; }}

QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {BORDER_STRONG}; background: {WHITE};
}}
QCheckBox::indicator:hover {{ border-color: {LEAF}; }}
QCheckBox::indicator:checked {{
    background: {LEAF}; border-color: {LEAF};
    image: url("{CHECK_ICON}");
}}

/* ---- buttons: one radius ({rad}px) everywhere, so corners are consistent ---- */
QPushButton {{
    border-radius: {rad}px; padding: 10px 18px; font-size: 10.5pt; font-weight: 600;
}}
/* Primary buttons match GEE-Assist-Web: a solid accent fill that changes with the theme,
   darken on hover, and a small downward nudge on press (Qt has no CSS transitions). */
QPushButton#PrimaryButton {{
    color: {ACCENT_TEXT}; border: none; border-radius: {rad}px; background: {ACCENT_SOLID};
}}
QPushButton#PrimaryButton:hover {{ background: {ACCENT_SOLID_HOVER}; }}
QPushButton#PrimaryButton:pressed {{ background: {ACCENT_SOLID_HOVER}; padding-top: 11px; padding-bottom: 9px; }}
QPushButton#PrimaryButton:disabled {{
    color: {PRIMARY_DISABLED_TEXT}; background: {PRIMARY_DISABLED_FROM};  /* solid, like every button */
}}
QPushButton#SecondaryButton {{
    color: {INK}; background: {WHITE}; border: 1px solid {BORDER_STRONG}; border-radius: {rad}px;
}}
QPushButton#SecondaryButton:hover {{ background: {FOAM}; border-color: {INK}; }}
QPushButton#SecondaryButton:pressed {{ background: {MINT}; padding-top: 11px; padding-bottom: 9px; }}
QPushButton#SecondaryButton:disabled {{ color: {SUBTLE}; border-color: {BORDER}; }}
QPushButton#DangerButton {{
    color: {ERROR}; background: {WHITE}; border: 1px solid {ERROR_BORDER};
}}
QPushButton#DangerButton:hover {{ background: {ERROR_BG}; }}
QPushButton#DangerButton:disabled {{ color: {SUBTLE}; border-color: {BORDER}; }}
QPushButton#LinkButton {{
    color: {OCEAN}; background: transparent; border: none; padding: 2px 4px; font-weight: 600;
}}
QPushButton#LinkButton:hover {{ color: {OCEAN_DARK}; text-decoration: underline; }}
QPushButton#LinkButton:disabled {{ color: {SUBTLE}; }}

QProgressBar#BusyBar {{
    background: {MINT}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px;
}}
QProgressBar#BusyBar::chunk {{
    border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_FROM}, stop:1 {ACCENT_TO});
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""

    # Pop-up menus (the account menu, the menu bar's menus).
    MENU_STYLE = f"""
QMenu {{ background: {WHITE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ color: {INK}; padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {FOAM}; }}
QMenu::item:disabled {{ color: {SUBTLE}; }}
"""


refresh()  # build the colour constants and stylesheets for the saved theme at import


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont(SANS, 10))
    app.setStyleSheet(STYLESHEET)
