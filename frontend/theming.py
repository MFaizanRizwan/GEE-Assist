"""Live theme switching — change the theme with no restart.

The theme used to be fixed at start-up, so switching it restarted the app. Here the
palette is swapped in place, every colour constant and stylesheet is rebuilt, and each
open widget re-applies its stylesheet. Widgets opt in with :func:`styled`, which sets
their stylesheet now and again on every theme change.

The registry is plain Python holding widgets by weak reference: it never keeps a
widget alive, never outlives a QApplication badly, and drops widgets Qt has deleted.

(The *layout* still restarts, because the window is built differently per layout.)
"""

from __future__ import annotations

import weakref
from typing import Callable

from PyQt6.QtWidgets import QApplication, QWidget

from frontend import accent, appearance, palette

# Each entry re-applies one widget's stylesheet; it returns False once its widget is gone.
_listeners: list[Callable[[], bool]] = []


def _compose(build: Callable[[], str]) -> str:
    """The widget's own stylesheet, plus Layout 3's field-book rules on any selector-based sheet
    (a page's or a dialog's), so every page reads as part of the same book."""
    css = build()
    if "{" in css:
        from frontend import fieldbook  # late: fieldbook imports theme

        if fieldbook.active():
            css += fieldbook.overlay()
    return css


def styled(widget: QWidget, build: Callable[[], str]) -> QWidget:
    """Set ``widget``'s stylesheet from ``build()`` now, and again on every theme change.

    ``build`` must read the current theme values (e.g. call a module's stylesheet
    function) so it returns freshly-coloured CSS each time.
    """
    widget.setStyleSheet(_compose(build))
    ref = weakref.ref(widget)

    def apply() -> bool:
        target = ref()
        if target is None:
            return False
        try:
            target.setStyleSheet(_compose(build))
        except RuntimeError:  # the C++ widget was deleted
            return False
        return True

    _listeners.append(apply)
    return widget


def on_theme_changed(callback: Callable[[], None]) -> None:
    """Run ``callback`` after every live theme change (for things that are not stylesheets).

    A bound method is held weakly, so subscribing never keeps its object alive.
    """
    ref = weakref.WeakMethod(callback) if hasattr(callback, "__self__") else (lambda: callback)

    def call() -> bool:
        target = ref()
        if target is None:
            return False
        try:
            target()
        except RuntimeError:  # it belonged to a deleted widget
            return False
        return True

    _listeners.append(call)


def set_theme(name: str, *, persist: bool = True) -> None:
    """Switch the theme live: swap the palette, rebuild everything, re-apply across the app."""
    from frontend import form_theme, theme  # late import avoids an import cycle

    if name not in palette.PALETTES:
        raise ValueError(f"Unknown theme: {name!r}")
    palette.set_theme(name)
    from frontend import fieldbook  # Layout 3's spine follows the theme (read by the terminal below)
    from frontend.gkonsol import colors as gkonsol_colors  # the terminal follows the theme too

    fieldbook.refresh()
    accent.refresh()
    theme.refresh()
    form_theme.refresh()
    gkonsol_colors.refresh()

    app = QApplication.instance()
    if app is not None:
        form_theme.apply_palette(app)  # Fusion QPalette + colour scheme
        theme.apply_theme(app)         # the global stylesheet
    if persist:
        appearance.save_theme(name)
    _listeners[:] = [listener for listener in list(_listeners) if listener()]
    if app is not None:
        for widget in app.allWidgets():  # painter-drawn widgets (charts, canvases) read theme.* on paint
            widget.update()
