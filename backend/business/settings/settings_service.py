"""Settings each user of a deployed copy enters: kept on this computer and applied without restarting."""

from __future__ import annotations

from typing import Callable

from backend.business.settings.i_settings_service import ISettingsService
from backend.business.settings.settings_rules import gee_project_error, gemini_key_error, key_hint, session_error
from backend.data.i_data_facade import IDataFacade
from backend.data.settings_store import ISettingsStore, SettingsStoreError
from backend.dto.settings_dto import AppSettingsDTO, AppSettingsUpdateDTO
from backend.dto.validation_dto import ValidationDTO


class SettingsService(ISettingsService):
    def __init__(
        self,
        store: ISettingsStore,
        data_facade: IDataFacade,
        env_defaults: dict | None = None,
        on_session_duration: Callable[[float], None] | None = None,
    ):
        """``env_defaults``: values from ``.env`` ("gee_project", "gemini_api_key", "session_duration"), used
        where nothing was saved. ``on_session_duration`` is told the "Keep me signed in" length."""
        self._store = store
        self._data_facade = data_facade
        self._env = {k: v for k, v in (env_defaults or {}).items() if v}
        self._on_session_duration = on_session_duration
        self._values = {**self._env, **self._store.load()}
        self._apply()

    def get_settings(self) -> AppSettingsDTO:
        key = self._values.get("gemini_api_key", "")
        return AppSettingsDTO(
            gee_project=self._values.get("gee_project", ""),
            gemini_key_set=bool(key),
            gemini_key_hint=key_hint(key),
            session_duration=float(self._values.get("session_duration", AppSettingsDTO.session_duration)),
        )

    def save_settings(self, update: AppSettingsUpdateDTO) -> ValidationDTO:
        result = ValidationDTO()
        project = update.gee_project.strip()
        key = update.gemini_api_key.strip()
        checks = {
            "gee_project": gee_project_error(project),
            "gemini_api_key": gemini_key_error(key, required=not self._values.get("gemini_api_key")),
            "session_duration": session_error(update.session_duration),
        }
        for field, message in checks.items():
            if message:
                result.add_error(field, message)
        if not result.is_valid:
            return result
        try:
            self._store.save(project, float(update.session_duration), key or None)
        except (SettingsStoreError, OSError) as exc:
            result.add_error("form", str(exc) if isinstance(exc, SettingsStoreError)
                             else f"The settings could not be saved: {exc.strerror or exc}")
            return result
        self._values.update(gee_project=project, session_duration=float(update.session_duration))
        if key:
            self._values["gemini_api_key"] = key
        self._apply()
        result.message = "Settings saved. They are used straight away."
        return result

    def _apply(self) -> None:
        """Hand the values to the clients (and the sign-in) that use them."""
        self._data_facade.configure_gee_project(self._values.get("gee_project", ""))
        self._data_facade.configure_gemini_key(self._values.get("gemini_api_key", ""))
        if self._on_session_duration is not None and "session_duration" in self._values:
            self._on_session_duration(float(self._values["session_duration"]))
