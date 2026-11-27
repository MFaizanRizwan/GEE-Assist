"""Bundled application fonts and the type scale, registered once at start-up.

The UI ships with the same three open-source families as GEE-Assist-Web, so the desktop
app and the website read as one product and look the same on every machine:

* **Sora** — the display family, used for headings and warnings.
* **Work Sans** — the body family, used for paragraphs, labels and controls.
* **IBM Plex Mono** — figures and measurements (Layout 3's one numeric face).

Sizes follow the website's golden-ratio scale (φ ≈ 1.618): each reading level is φ times
the one below it, with √φ half-steps between. Qt Style Sheets size text in points, so the
scale is in points, on a 10pt body:

    XS 8 · SM 9 · MD 10 (body) · LG 12.7 (×√φ) · XL 16.2 (×φ) · XXL 20.6 (×φ√φ) · HERO 26.2 (×φ²)

XS and SM are small UI type (hints, captions, table cells) and sit below the scale, as
``--text-xs`` / ``--text-sm`` do on the website.

``load_fonts`` must run after a ``QApplication`` exists and before any widget is
shown. If the files are missing (or fail to register), the names below still fall
back to system fonts, so the app never breaks over typography.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase

_FONTS_DIR = Path(__file__).resolve().parent / "resources" / "fonts"

# The families the bundled files register as (confirmed with QFontDatabase).
DISPLAY = "Sora"            # headings
BODY = "Work Sans"          # paragraphs, labels, controls
WARNING = "Sora"            # banners / field errors — distinct from body text
MONO = "IBM Plex Mono"      # figures and measurements

# Used when the bundled files are unavailable, so the stylesheets still resolve.
FALLBACK_DISPLAY = "Segoe UI Semibold"
FALLBACK_BODY = "Segoe UI"

# ---- the golden-ratio type scale, in points
RATIO = 1.618
MD = 10                                  # body text
XS = 8                                   # hints, captions
SM = 9                                   # small UI, table cells
LG = round(MD * RATIO ** 0.5, 1)         # 12.7 — section titles
XL = round(MD * RATIO, 1)                # 16.2 — dialog titles, stat values
XXL = round(MD * RATIO ** 1.5, 1)        # 20.6 — page titles
HERO = round(MD * RATIO ** 2, 1)         # 26.2 — the sign-in headline

_FILES = (
    "Sora.ttf", "WorkSans.ttf", "WorkSans-Italic.ttf",
    "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf", "IBMPlexMono-SemiBold.ttf", "IBMPlexMono-Bold.ttf",
)
_loaded = False


def load_fonts() -> bool:
    """Register the bundled fonts with Qt. Safe to call more than once.

    Returns True if every bundled file registered. On failure the family names
    stay pointed at the system fallbacks, so callers never need to branch.
    """
    global _loaded, DISPLAY, BODY, WARNING
    if _loaded:
        return True

    ok = True
    for name in _FILES:
        path = _FONTS_DIR / name
        if not path.exists() or QFontDatabase.addApplicationFont(str(path)) < 0:
            ok = False

    # Glyphs the bundled faces lack (✦, arrows, symbols) fall back to Windows' symbol faces.
    for family in (DISPLAY, BODY, MONO):
        QFont.insertSubstitutions(family, ["Segoe UI", "Segoe UI Symbol", "Segoe UI Emoji"])

    if not ok:
        DISPLAY = FALLBACK_DISPLAY
        BODY = FALLBACK_BODY
        WARNING = FALLBACK_DISPLAY
    _loaded = ok
    return ok
