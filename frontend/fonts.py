"""Bundled application fonts, registered once at start-up.

The UI ships with two open-source families so it looks the same on every machine,
instead of depending on whatever the user happens to have installed:

* **Space Grotesk** — the display family, used for headings and warnings. A
  geometric sans with real character, so titles read as a deliberate choice
  rather than the system default.
* **Inter** — the body family, used for paragraphs, labels and controls. Quiet,
  highly legible at small sizes.

``load_fonts`` must run after a ``QApplication`` exists and before any widget is
shown. If the files are missing (or fail to register), the names below still fall
back to the previous system fonts, so the app never breaks over typography.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase

_FONTS_DIR = Path(__file__).resolve().parent / "resources" / "fonts"

# The families the bundled files register as (confirmed with QFontDatabase).
DISPLAY = "Space Grotesk"   # headings
BODY = "Inter"              # paragraphs, labels, controls
WARNING = "Space Grotesk"   # banners / field errors — distinct from body text
MONO = "JetBrains Mono"     # figures and measurements (Layout 3's one numeric face)

# Used when the bundled files are unavailable, so the stylesheets still resolve.
FALLBACK_DISPLAY = "Georgia"
FALLBACK_BODY = "Segoe UI"

_FILES = ("Inter.ttf", "SpaceGrotesk.ttf", "JetBrainsMono.ttf")
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
