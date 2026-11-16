"""Settings each user of a deployed copy enters: Earth Engine project, Gemini API key, session length."""

import json
from unittest.mock import MagicMock

import pytest

from backend.business.settings import SettingsService
from backend.business.settings.settings_rules import gee_project_error, gemini_key_error, key_hint
from backend.data.clients.gee_client import GEEClient
from backend.data.clients.gemini_client import GeminiClient
from backend.data.settings_store import LocalSettingsStore, MemorySettingsStore, SettingsStoreError
from backend.dto.settings_dto import AppSettingsDTO, AppSettingsUpdateDTO
from backend.exceptions import GEESetupError, LLMServiceError

KEY = "AIzaSyD-thisIsAFakeKeyForTests_123456"


# ------------------------------------------------------------- rules
@pytest.mark.parametrize(("project", "ok"), [
    ("my-gee-project-123", True), ("ee-abdullah", True), ("", False), ("My Project", False),
    ("abc", False), ("1starts-with-digit", False), ("ends-with-", False), ("UPPER-case-id", False),
])
def test_project_ids_follow_google_clouds_rules(project, ok):
    assert (gee_project_error(project) is None) == ok


def test_gemini_keys_are_checked_loosely():
    assert gemini_key_error(KEY, required=True) is None
    assert gemini_key_error("", required=True) == "Enter your Gemini API key"
    assert gemini_key_error("", required=False) is None  # keep the saved one
    assert "spaces" in gemini_key_error("AIza abc", required=True)
    assert "too short" in gemini_key_error("AIza123", required=True)
    assert key_hint(KEY) == "…3456"


# ------------------------------------------------------------- store
@pytest.fixture
def fake_keyring(monkeypatch):
    import keyring

    vault = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: vault.get((service, name)))
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: vault.__setitem__((service, name), value))
    return vault


def test_the_key_goes_to_the_credential_store_and_the_rest_to_json(tmp_path, fake_keyring):
    store = LocalSettingsStore(tmp_path / "app_settings.json", "GEE-Assist-test")
    store.save("my-gee-project-123", 3 * 86400, KEY)
    assert fake_keyring[("GEE-Assist-test", "gemini_api_key")] == KEY
    stored = json.loads((tmp_path / "app_settings.json").read_text())
    assert stored == {"gee_project": "my-gee-project-123", "session_duration": 3 * 86400}
    assert KEY not in (tmp_path / "app_settings.json").read_text()  # never in a plain file
    assert store.load() == {"gee_project": "my-gee-project-123", "session_duration": 3 * 86400, "gemini_api_key": KEY}
    store.save("other-project-1", 86400)  # no key given: the saved one stays
    assert store.load()["gemini_api_key"] == KEY


def test_a_store_that_cannot_keep_the_key_says_so(tmp_path, monkeypatch):
    import keyring

    def broken(*args):
        raise RuntimeError("no backend")

    monkeypatch.setattr(keyring, "set_password", broken)
    with pytest.raises(SettingsStoreError, match="credential store"):
        LocalSettingsStore(tmp_path / "s.json", "x").save("my-gee-project-123", 86400, KEY)


# ------------------------------------------------------------- service
def _service(saved=None, env=None):
    data, durations = MagicMock(), []
    service = SettingsService(MemorySettingsStore(saved), data, env_defaults=env, on_session_duration=durations.append)
    return service, data, durations


def test_a_new_copy_without_env_asks_for_both():
    service, data, _ = _service()
    assert service.get_settings().missing == ["gee_project", "gemini_api_key"]
    data.configure_gee_project.assert_called_with("")


def test_env_values_are_used_until_settings_are_saved():
    service, data, _ = _service(env={"gee_project": "env-project-1", "gemini_api_key": KEY})
    settings = service.get_settings()
    assert settings.missing == [] and settings.gee_project == "env-project-1" and settings.gemini_key_hint == "…3456"
    data.configure_gemini_key.assert_called_with(KEY)


def test_saved_values_win_over_env():
    service, data, durations = _service(saved={"gee_project": "saved-project-1", "session_duration": 86400.0},
                                        env={"gee_project": "env-project-1"})
    assert service.get_settings().gee_project == "saved-project-1" and durations == [86400.0]


def test_saving_applies_at_once():
    service, data, durations = _service()
    result = service.save_settings(AppSettingsUpdateDTO("my-gee-project-123", f"  {KEY} ", 14 * 86400))
    assert result.is_valid and "straight away" in result.message
    data.configure_gee_project.assert_called_with("my-gee-project-123")
    data.configure_gemini_key.assert_called_with(KEY)
    assert durations[-1] == 14 * 86400
    assert service.get_settings() == AppSettingsDTO("my-gee-project-123", True, "…3456", 14 * 86400)


def test_mistakes_are_reported_per_field_and_nothing_is_saved():
    service, data, _ = _service()
    result = service.save_settings(AppSettingsUpdateDTO("My Project", "", 0))
    assert set(result.errors) == {"gee_project", "gemini_api_key", "session_duration"}
    assert service.get_settings().missing == ["gee_project", "gemini_api_key"]


def test_an_empty_key_keeps_the_saved_one():
    service, data, _ = _service(saved={"gemini_api_key": KEY})
    assert service.save_settings(AppSettingsUpdateDTO("my-gee-project-123", "", 7 * 86400)).is_valid
    assert service.get_settings().gemini_key_set
    data.configure_gemini_key.assert_called_with(KEY)


# ------------------------------------------------------------- clients take new values without restarting
def test_the_earth_engine_client_reconnects_with_a_new_project():
    client = GEEClient(project="")
    with pytest.raises(GEESetupError, match="Options → Settings"):
        client._initialize()
    client._initialized = True
    client.set_project("my-gee-project-123")
    assert client._project == "my-gee-project-123" and not client._initialized


def test_the_gemini_client_uses_a_new_key():
    client = GeminiClient(api_key="", model="m")
    with pytest.raises(LLMServiceError, match="Options → Settings"):
        client._sdk()
    client._client = object()
    client.set_api_key(KEY)
    assert client._api_key == KEY and client._client is None


def test_the_business_facade_hands_settings_to_the_settings_service():
    from backend.business.facade import BusinessFacade

    settings = MagicMock()
    facade = BusinessFacade(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings_service=settings)
    assert facade.get_app_settings() is settings.get_settings.return_value
    update = AppSettingsUpdateDTO("my-gee-project-123")
    assert facade.save_app_settings(update) is settings.save_settings.return_value
    settings.save_settings.assert_called_once_with(update)
