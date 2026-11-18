from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.settings_dto import AppSettingsDTO, AppSettingsUpdateDTO
from backend.dto.validation_dto import ValidationDTO


class ISettingsService(ABC):
    """The settings each user of a deployed copy provides: Earth Engine project, Gemini key, session length.

    Saved values come first; the ``.env`` file only fills what was never saved (handy while developing).
    """

    @abstractmethod
    def get_settings(self) -> AppSettingsDTO: ...

    @abstractmethod
    def save_settings(self, update: AppSettingsUpdateDTO) -> ValidationDTO:
        """Check, save on this computer and apply at once. Field problems come back in ``errors``
        (keys "gee_project", "gemini_api_key", "session_duration")."""
