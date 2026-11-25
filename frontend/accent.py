"""The primary-button accent, in one place, matching GEE-Assist-Web.

On the website every primary button is a **solid** colour (``var(--leaf)``) with
``var(--on-primary)`` text — and both change with the theme. We mirror that: the
accent is the active theme's ``LEAF`` with ``PRIMARY_TEXT`` on it, in **every**
layout, so switching the theme always recolours the buttons. (Layouts differ by
structure and surfaces, not by button hue.)

``refresh()`` recomputes the values after ``palette.set_theme`` for live theme
switching. ``FROM`` / ``TO`` stay equal to ``SOLID`` so any remaining gradient
button rule renders flat.
"""

from __future__ import annotations

from frontend import palette

# One radius for every button, so corners are consistent across the whole app.
BUTTON_RADIUS = 10


def _resolve() -> tuple[str, str, str]:
    # Each palette names its own button fill (contrast-checked against PRIMARY_TEXT). The light
    # theme's is its darker leaf, since white on its LEAF would be only ~3.5:1.
    p = palette.ACTIVE
    return p["BUTTON"], p["BUTTON_HOVER"], p["PRIMARY_TEXT"]


SOLID = SOLID_HOVER = TEXT = SOLID_PRESSED = SOFT = FROM = TO = FROM_HOVER = TO_HOVER = ""


def refresh() -> None:
    """Recompute the accent from the active palette (after a theme change)."""
    global SOLID, SOLID_HOVER, TEXT, SOLID_PRESSED, SOFT, FROM, TO, FROM_HOVER, TO_HOVER
    SOLID, SOLID_HOVER, TEXT = _resolve()
    SOLID_PRESSED = SOLID_HOVER          # Qt can't translate on press; a darker fill reads similarly
    SOFT = palette.ACTIVE["ACCENT_SOFT"]  # faint tint for secondary hovers / selections
    FROM = TO = SOLID
    FROM_HOVER = TO_HOVER = SOLID_HOVER


refresh()
