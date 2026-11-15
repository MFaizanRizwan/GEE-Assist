"""The settings dialog: first run of a new copy, and Options > Settings… (offscreen)."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from backend.business.settings import SettingsService  # noqa: E402
from backend.data.settings_store import MemorySettingsStore  # noqa: E402
from frontend.views.settings_dialog import SettingsDialog, duration_label, settings_needed  # noqa: E402

KEY = "AIzaSyD-thisIsAFakeKeyForTests_123456"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Facade:
    """The settings part of the business facade, on a real SettingsService."""

    def __init__(self, saved=None):
        from unittest.mock import MagicMock

        self.data = MagicMock()
        self.service = SettingsService(MemorySettingsStore(saved), self.data)

    def get_app_settings(self):
        return self.service.get_settings()

    def save_app_settings(self, update):
        return self.service.save_settings(update)


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_new_copy_needs_both_settings(app):
    facade = Facade()
    assert settings_needed(facade) == ["gee_project", "gemini_api_key"]
    assert settings_needed(Facade({"gee_project": "my-gee-project-123", "gemini_api_key": KEY})) == []


def test_first_run_shows_how_to_get_them_and_saves_them(app):
    facade = Facade()
    dialog = SettingsDialog(facade, first_run=True)
    assert dialog.windowTitle() == "Set up GEE-Assist" and dialog.save_button.text() == "Save and continue"
    assert not dialog.project_help.steps.isHidden() and not dialog.key_help.steps.isHidden()
    steps = dialog.project_help.steps.text()
    assert "code.earthengine.google.com/register" in steps and "Project ID" in steps
    assert "aistudio.google.com/apikey" in dialog.key_help.steps.text()

    dialog.project_field.set_text("my-gee-project-123")
    dialog.key_field.set_text(KEY)
    dialog.save_button.click()
    assert wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert settings_needed(facade) == []
    facade.data.configure_gee_project.assert_called_with("my-gee-project-123")


def test_first_run_cannot_be_dismissed_except_by_signing_out(app):
    dialog = SettingsDialog(Facade(), first_run=True)
    dialog.show()
    dialog.reject()
    QApplication.sendEvent(dialog, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    dialog.close()
    assert dialog.isVisible()
    signed_out = []
    dialog.sign_out_requested.connect(lambda: signed_out.append(True))
    dialog.other_button.click()  # "Sign out"
    assert signed_out and not dialog.isVisible()


def test_mistakes_show_under_their_fields(app):
    dialog = SettingsDialog(Facade(), first_run=True)
    dialog.project_field.set_text("My Project")
    dialog.save_button.click()
    assert wait_until(lambda: dialog.project_field.has_error())
    assert "project ID" in dialog.project_field.message.text()
    assert dialog.key_field.has_error() and dialog.result() == 0


def test_settings_later_keep_the_saved_key_unless_a_new_one_is_pasted(app):
    facade = Facade({"gee_project": "my-gee-project-123", "gemini_api_key": KEY, "session_duration": 86400.0})
    dialog = SettingsDialog(facade)
    assert dialog.windowTitle() == "Settings" and dialog.other_button.text() == "Cancel"
    assert dialog.project_field.text() == "my-gee-project-123" and dialog.key_field.text() == ""
    assert "…3456" in dialog.key_field.message.text() and dialog.session_box.currentText() == "1 day"
    assert dialog.project_help.steps.isHidden()  # folded away after the first run
    dialog.project_field.set_text("another-project-9")
    dialog.session_box.setCurrentIndex(dialog.session_box.findText("30 days"))
    dialog.save_button.click()
    assert wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    settings = facade.get_app_settings()
    assert (settings.gee_project, settings.gemini_key_hint, settings.session_duration) == (
        "another-project-9", "…3456", 30 * 86400)


def test_a_session_length_from_env_that_is_not_listed_is_kept(app):
    dialog = SettingsDialog(Facade({"gee_project": "my-gee-project-123", "gemini_api_key": KEY,
                                    "session_duration": 120.0}))
    assert dialog.session_box.currentText() == "2 minutes"
    assert duration_label(12 * 3600) == "12 hours" and duration_label(86400) == "1 day"


def test_the_window_asks_on_first_run_and_from_the_options_menu(app, monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from backend.business.facade import IBusinessFacade
    from backend.dto.settings_dto import AppSettingsDTO
    from backend.dto.user_dto import UserDTO
    from frontend.gkonsol.history import GkonsolStore
    from frontend.views import home_window
    from tests.test_dashboard import StubQueryWorkspace

    monkeypatch.setattr(home_window, "MainWindow", StubQueryWorkspace)
    monkeypatch.setattr(home_window, "GkonsolStore", lambda: GkonsolStore(tmp_path / "gkonsol.json"))
    facade = MagicMock(spec=IBusinessFacade)
    facade.list_downloads.return_value = []
    facade.get_chunk_size_mb.return_value = 500
    facade.get_current_project.return_value = None
    facade.list_projects.return_value = []
    facade.get_app_settings.return_value = AppSettingsDTO()  # nothing entered yet
    asked = []
    monkeypatch.setattr(home_window.HomeWindow, "exec_settings",
                        lambda window, first_run: asked.append(first_run) or True)
    window = home_window.HomeWindow(facade, UserDTO(id="1", username="a", full_name="A B", role="user"))
    assert wait_until(lambda: asked == [True])  # asked as soon as the window is up
    window.menu_bar.app_settings.trigger()
    assert asked == [True, False]
    window.terminal.shutdown()
    window.deleteLater()
