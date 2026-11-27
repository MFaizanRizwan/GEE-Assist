"""Live theme switching stays quick: the Qt style is set once, never rebuilt on a switch."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend import palette, theming  # noqa: E402
from frontend.form_theme import apply_palette  # noqa: E402
from frontend.theme import apply_theme  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_a_live_theme_change_does_not_rebuild_the_qt_style(monkeypatch):
    apply_palette(app)
    apply_theme(app)  # start-up: Fusion is set here, once
    calls = []
    original = QApplication.setStyle
    monkeypatch.setattr(QApplication, "setStyle", lambda *a: (calls.append(a), original(*a))[1])
    start = palette.THEME
    try:
        for name in ("navy", "light"):
            theming.set_theme(name, persist=False)
    finally:
        theming.set_theme(start, persist=False)
    # Setting a style re-polishes every widget: it made each switch take ~10 s in the full window.
    assert calls == []
