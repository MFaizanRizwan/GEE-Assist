"""Checks for the settings a user enters, so mistakes show at once instead of on the first download."""

from __future__ import annotations

import re

# Google Cloud project IDs: 6-30 characters, lowercase letters, digits and hyphens, starting with a letter
# and not ending with a hyphen (https://cloud.google.com/resource-manager/docs/creating-managing-projects).
PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")

# "Keep me signed in" lengths offered, in seconds.
SESSION_CHOICES: tuple[tuple[str, float], ...] = (
    ("1 day", 86400.0), ("3 days", 3 * 86400.0), ("7 days", 7 * 86400.0),
    ("14 days", 14 * 86400.0), ("30 days", 30 * 86400.0),
)
MIN_SESSION = 60.0
MAX_SESSION = 90 * 86400.0


def gee_project_error(value: str) -> str | None:
    project = value.strip()
    if not project:
        return "Enter your Earth Engine project ID"
    if " " in project or any(c.isupper() for c in project):
        return "Use the project ID (lowercase, no spaces), not the project's display name"
    if not PROJECT_ID.fullmatch(project):
        return ("A project ID has 6-30 lowercase letters, digits or hyphens, starts with a letter "
                "and does not end with a hyphen, e.g. my-gee-project-123")
    return None


def gemini_key_error(value: str, required: bool) -> str | None:
    key = value.strip()
    if not key:
        return "Enter your Gemini API key" if required else None
    if any(c.isspace() for c in key):
        return "The key has no spaces: copy it again from Google AI Studio"
    if len(key) < 30:
        return "This is too short to be a Gemini API key: copy the whole key from Google AI Studio"
    return None


def session_error(seconds: float) -> str | None:
    if not MIN_SESSION <= seconds <= MAX_SESSION:
        return "Choose between 1 minute and 90 days"
    return None


def key_hint(key: str) -> str:
    """The last few characters, to recognise a saved key without showing it."""
    return f"…{key[-4:]}" if len(key) >= 8 else ""
