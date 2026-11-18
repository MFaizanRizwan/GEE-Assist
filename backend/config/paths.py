r"""Filesystem roots that work both in development and in a frozen build.

In development both roots are the project folder, so files live in ``./assets``
and ``./workspace`` exactly as before.

In a frozen (PyInstaller) build:
  * ``BUNDLE_ROOT`` is the PyInstaller extraction dir - read-only bundled files
    such as ``assets`` and ``frontend/resources``.
  * ``DATA_ROOT`` is ``%APPDATA%\GEE-Assist`` - persistent, writable, per-user
    data (settings, project history, profile photos, downloads).

The extraction dir must never be used for writes: in one-file mode it is a
temporary folder that Windows deletes when the app exits, which would lose the
user's settings and projects on every run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: True when running inside a PyInstaller-built executable.
FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # Read-only bundled files live in the extraction dir (sys._MEIPASS); fall back
    # to the executable's own folder if that attribute is ever missing.
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    # Writable user data goes to %APPDATA%\GEE-Assist (persistent across runs).
    _appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
    DATA_ROOT = Path(_appdata) / "GEE-Assist"
else:
    _PROJECT = Path(__file__).resolve().parents[2]
    BUNDLE_ROOT = _PROJECT
    DATA_ROOT = _PROJECT
