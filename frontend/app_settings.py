"""The user's settings (Earth Engine project, Gemini key, session length) as the UI shows them."""

from __future__ import annotations

from backend.dto.settings_dto import AppSettingsDTO
from backend.exceptions import GeeAssistError

SETTINGS_PLACE = "Options → Settings…"


def current_settings(facade) -> AppSettingsDTO:
    """What is set now. Without a settings service (some builds and tests), the values from .env."""
    try:
        settings = facade.get_app_settings()
    except GeeAssistError:
        settings = None
    if isinstance(settings, AppSettingsDTO):
        return settings
    from backend.business.settings.settings_rules import key_hint
    from backend.config.llm import load_llm_settings
    from backend.config.settings import get_settings

    env, key = get_settings(), load_llm_settings().api_key
    return AppSettingsDTO(env.gee_project, bool(key), key_hint(key), env.session_duration)
