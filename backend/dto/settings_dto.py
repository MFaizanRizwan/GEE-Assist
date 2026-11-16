"""The app's own settings that each user of a deployed copy provides: their Earth Engine project,
their Gemini API key and how long "Keep me signed in" lasts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettingsDTO:
    """What is set now. The Gemini key itself is never handed to the UI, only whether there is one."""

    gee_project: str = ""
    gemini_key_set: bool = False
    gemini_key_hint: str = ""                   # its last characters, e.g. "…x7Qa", to recognise it
    session_duration: float = 7 * 24 * 3600     # seconds

    @property
    def missing(self) -> list[str]:
        """The settings the app cannot do without, still empty ("gee_project", "gemini_api_key")."""
        return [name for name, ok in (("gee_project", bool(self.gee_project)),
                                      ("gemini_api_key", self.gemini_key_set)) if not ok]


@dataclass(frozen=True)
class AppSettingsUpdateDTO:
    """What the user entered. An empty ``gemini_api_key`` keeps the key already saved."""

    gee_project: str
    gemini_api_key: str = ""
    session_duration: float = 7 * 24 * 3600
