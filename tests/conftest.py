"""Shared test set-up."""

import os

# The tests run in the light theme, whatever theme is saved on this computer.
os.environ.setdefault("GEE_ASSIST_THEME", "light")
# ... and in the classical layout, whatever layout is saved (or being tried) on this computer.
os.environ.setdefault("GEE_ASSIST_LAYOUT", "classical")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _back_to_the_light_theme():
    """The theme now switches live, in this process: a test that switches it must not leave
    every later test running in that theme. Put the light theme back (without saving it)."""
    yield
    from frontend import palette

    if palette.THEME != "light":
        from frontend import theming

        theming.set_theme("light", persist=False)
