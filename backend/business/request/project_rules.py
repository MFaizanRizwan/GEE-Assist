"""What a project name may be: it becomes a folder name, so it must be one Windows, macOS and Linux accept."""

from __future__ import annotations

import re
from pathlib import Path

NAME_MAX_LENGTH = 80
DEFAULT_NAME = "Project"
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def clean_project_name(name: str) -> str:
    return " ".join(name.split())


def project_name_error(name: str) -> str | None:
    """Why ``name`` cannot be a project (folder) name, or None if it can."""
    name = clean_project_name(name)
    if not name:
        return "Enter a project name"
    if len(name) > NAME_MAX_LENGTH:
        return f"Use at most {NAME_MAX_LENGTH} characters"
    if _FORBIDDEN.search(name):
        return 'A project name cannot contain < > : " / \\ | ? *'
    if name.endswith("."):
        return "A project name cannot end with a full stop"
    if name in (".", "..") or name.split(".")[0].upper() in _RESERVED:
        return f"'{name}' is reserved by Windows; choose another name"
    return None


def default_project_name(location: str) -> str:
    """The name used when none is given: "Project 1", or the first of "Project 2", "Project 3", ...
    that is not a folder in ``location`` yet."""
    parent = Path(location).expanduser() if location and location.strip() else None
    taken = set()
    if parent is not None and parent.is_dir():
        taken = {child.name.lower() for child in parent.iterdir()}
    number = 1
    while f"{DEFAULT_NAME} {number}".lower() in taken:
        number += 1
    return f"{DEFAULT_NAME} {number}"
