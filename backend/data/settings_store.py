"""Keeps the settings each user of a deployed copy enters on this computer.

The Gemini API key is a secret: it goes into the operating system's credential store (Windows
Credential Manager, macOS Keychain, Secret Service) through ``keyring``, like the saved sign-in.
The Earth Engine project and the session length are not secret: they go into a JSON file.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GEMINI_KEY = "gemini_api_key"


class SettingsStoreError(Exception):
    """The settings could not be saved (e.g. no usable credential store for the key)."""


class ISettingsStore(ABC):
    @abstractmethod
    def load(self) -> dict[str, Any]:
        """The saved values: any of "gee_project", "gemini_api_key", "session_duration" (missing = never saved)."""

    @abstractmethod
    def save(self, gee_project: str, session_duration: float, gemini_api_key: str | None = None) -> None:
        """Save the values; ``gemini_api_key`` None keeps the saved key."""


class LocalSettingsStore(ISettingsStore):
    def __init__(self, path: Path | str, keyring_service: str):
        self._path = Path(path)
        self._service = keyring_service

    def load(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if isinstance(data.get("gee_project"), str):
                    values["gee_project"] = data["gee_project"]
                if isinstance(data.get("session_duration"), (int, float)) and data["session_duration"] > 0:
                    values["session_duration"] = float(data["session_duration"])
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logger.warning("App settings %s are not readable; using the defaults", self._path)
        key = self._get_key()
        if key:
            values["gemini_api_key"] = key
        return values

    def save(self, gee_project: str, session_duration: float, gemini_api_key: str | None = None) -> None:
        if gemini_api_key is not None:
            self._set_key(gemini_api_key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(json.dumps({"gee_project": gee_project, "session_duration": session_duration},
                                        indent=2), encoding="utf-8")
        os.replace(temporary, self._path)

    # ------------------------------------------------------------- credential store
    def _get_key(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(self._service, _GEMINI_KEY)
        except Exception:
            logger.warning("Could not read the Gemini key from the credential store", exc_info=True)
            return None

    def _set_key(self, value: str) -> None:
        try:
            import keyring

            keyring.set_password(self._service, _GEMINI_KEY, value)
        except Exception as exc:
            raise SettingsStoreError(
                "The Gemini API key could not be saved in this computer's credential store."
            ) from exc


class MemorySettingsStore(ISettingsStore):
    """Keeps nothing between launches. Used in tests."""

    def __init__(self, values: dict[str, Any] | None = None):
        self.values = dict(values or {})

    def load(self) -> dict[str, Any]:
        return dict(self.values)

    def save(self, gee_project: str, session_duration: float, gemini_api_key: str | None = None) -> None:
        self.values.update(gee_project=gee_project, session_duration=session_duration)
        if gemini_api_key is not None:
            self.values["gemini_api_key"] = gemini_api_key
