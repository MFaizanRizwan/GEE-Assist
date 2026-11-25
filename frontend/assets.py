"""Paths to the files in the project's ``assets`` folder."""

from __future__ import annotations

from pathlib import Path

from frontend import palette

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

STARTING_VIDEO = ASSETS_DIR / "starting_video" / "start.mp4"
EARTH_SVG = ASSETS_DIR / "resources" / "Satellite around Earth.svg"

_ICONS_DIR = ASSETS_DIR / "project_icon"
APP_ICONS = {  # the project icon drawn for each theme
    "light": _ICONS_DIR / "light_icon.png",
    "dark-green": _ICONS_DIR / "dark_blue_green_icon.png",
    "dark-grey": _ICONS_DIR / "dark_grey_icon.png",
}

def app_icon(theme: str):
    """The project icon for ``theme``: its own, else the light or dark one that suits its ground."""
    return APP_ICONS.get(theme) or APP_ICONS["dark-green" if theme in palette.DARK_THEMES else "light"]


APP_ICON = app_icon(palette.THEME)  # window, taskbar and side bar logo follow the theme
