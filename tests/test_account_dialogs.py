"""The account dialogs against a fake facade (no server, offscreen)."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from backend.auth_exceptions import SessionExpiredError  # noqa: E402
from backend.dto.user_dto import UserDTO  # noqa: E402
from backend.dto.validation_dto import ValidationDTO  # noqa: E402
from frontend.views.account_dialogs import (  # noqa: E402
    ChangePasswordDialog,
    CreateUserDialog,
    EditDetailsDialog,
)

ME = UserDTO(id="u1", username="ayesha", full_name="Ayesha Khan", role="user", email="ayesha@example.com",
             phone_number="+923001234567")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


class FakeFacade:
    def __init__(self, answer=None, error=None):
        self.answer = answer or ValidationDTO(message="Saved.")
        self.error = error
        self.calls = []

    def _reply(self, *call):
        self.calls.append(call)
        if self.error:
            raise self.error
        return self.answer

    def update_user(self, user):
        return self._reply("update", user)

    def change_password(self, user_id, new, confirm, current=None):
        return self._reply("password", user_id, new, confirm, current)

    def create_user(self, user):
        return self._reply("create", user)


def test_edit_sends_the_changed_details_and_closes(app):
    facade = FakeFacade(ValidationDTO(message="Your details were saved."))
    dialog = EditDetailsDialog(facade, ME)
    assert "email" not in dialog.fields  # your own email is not editable
    dialog.fields["full_name"].set_text("Ayesha Kiran Khan")
    dialog.save_button.click()
    assert wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    sent = facade.calls[0][1]
    assert sent.full_name == "Ayesha Kiran Khan" and sent.id == "u1" and sent.email == ME.email
    assert dialog.result_message == "Your details were saved."


def test_edit_shows_errors_under_their_fields_and_stays_open(app):
    invalid = ValidationDTO()
    invalid.add_error("username", "Username is already taken")
    invalid.add_error("form", "Something only the server knows")
    dialog = EditDetailsDialog(FakeFacade(invalid), ME)
    dialog.save_button.click()
    assert wait_until(lambda: dialog.fields["username"].has_error())
    assert dialog.fields["username"].message.text() == "Username is already taken"
    assert dialog.banner.text() == "Something only the server knows" and dialog.result() == 0
    assert dialog.save_button.isEnabled()


def test_admin_editing_someone_can_change_their_email(app):
    facade = FakeFacade()
    dialog = EditDetailsDialog(facade, ME, allow_email=True)
    dialog.fields["email"].set_text("new@example.com")
    dialog.save_button.click()
    assert wait_until(lambda: facade.calls)
    assert facade.calls[0][1].email == "new@example.com"


def test_expired_session_closes_the_dialog(app):
    dialog = EditDetailsDialog(FakeFacade(error=SessionExpiredError("expired", 401)), ME)
    expired = []
    dialog.session_expired.connect(lambda: expired.append(True))
    dialog.save_button.click()
    assert wait_until(lambda: expired) and dialog.result() == QDialog.DialogCode.Rejected


def test_change_own_password_sends_the_current_one(app):
    facade = FakeFacade()
    dialog = ChangePasswordDialog(facade, ME)
    dialog.fields["current_password"].set_text("OldPass123")
    dialog.fields["new_password"].set_text("NewPass123")
    dialog.fields["confirm_password"].set_text("NewPass123")
    dialog.save_button.click()
    assert wait_until(lambda: facade.calls)
    assert facade.calls[0] == ("password", "u1", "NewPass123", "NewPass123", "OldPass123")


def test_admin_reset_does_not_ask_for_the_current_password(app):
    facade = FakeFacade()
    dialog = ChangePasswordDialog(facade, ME, own=False)
    assert "current_password" not in dialog.fields
    dialog.fields["new_password"].set_text("Reset12345")
    dialog.fields["confirm_password"].set_text("Reset12345")
    dialog.save_button.click()
    assert wait_until(lambda: facade.calls)
    assert facade.calls[0] == ("password", "u1", "Reset12345", "Reset12345", None)


def test_create_user_checks_the_passwords_match_before_sending(app):
    facade = FakeFacade()
    dialog = CreateUserDialog(facade)
    for key, value in {"full_name": "Carol New", "email": "carol@example.com", "phone_number": "+923003333333",
                       "username": "carol", "password": "CarolPass1", "confirm_password": "Other"}.items():
        dialog.fields[key].set_text(value)
    dialog.save_button.click()
    assert dialog.fields["confirm_password"].has_error() and facade.calls == []
    dialog.fields["confirm_password"].set_text("CarolPass1")
    dialog.role.setCurrentIndex(1)
    dialog.save_button.click()
    assert wait_until(lambda: facade.calls)
    new = facade.calls[0][1]
    assert (new.username, new.password, new.role) == ("carol", "CarolPass1", "admin")
