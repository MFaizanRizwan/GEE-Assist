"""Which window layout the user chose, kept in ``workspace/layout.json``.

Two layouts share the same pages and logic, only arranged differently:

* ``classical`` — the original look: scrolling cards with a bottom action bar.
* ``modern`` — a full-height map beside a dark, tabbed parameter panel
  (Area · Data · Time · Output) with a prominent "Run analysis" button,
  inspired by web GIS consoles.

No file (or an unknown value in it) means the classical layout, which is the
default. The layout is read once at start-up and applied while the window is
built, so changing it restarts the app (as choosing a theme does).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parents[1] / "workspace" / "layout.json"

LAYOUTS = {                     # name -> label shown to the user
    "classical": "Layout 1",
    "modern": "Layout 2",
    "studio": "Layout 3",
}
DEFAULT_LAYOUT = "classical"


def saved_layout(path: Path = SETTINGS_FILE) -> str | None:
    """The layout the user chose, or None if they have not chosen one."""
    try:
        name = json.loads(Path(path).read_text(encoding="utf-8")).get("layout")
    except (OSError, ValueError, AttributeError):
        return None
    return name if name in LAYOUTS else None


def current_layout(path: Path = SETTINGS_FILE) -> str:
    # GEE_ASSIST_LAYOUT overrides the saved choice (e.g. for the tests, which must not read the
    # layout the user is trying in the app at the same time), as GEE_ASSIST_THEME does for the theme.
    override = os.environ.get("GEE_ASSIST_LAYOUT")
    if Path(path) == SETTINGS_FILE and override in LAYOUTS:
        return override
    return saved_layout(path) or DEFAULT_LAYOUT


def is_modern(path: Path = SETTINGS_FILE) -> bool:
    return current_layout(path) == "modern"


def is_studio(path: Path = SETTINGS_FILE) -> bool:
    return current_layout(path) == "studio"


def save_layout(name: str, path: Path = SETTINGS_FILE) -> None:
    if name not in LAYOUTS:
        raise ValueError(f"Unknown layout: {name!r}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"layout": name}, indent=2), encoding="utf-8")
