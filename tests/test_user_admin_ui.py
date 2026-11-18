"""Admin user-management dialog against a fake facade (no server, offscreen)."""

import dataclasses
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.auth_exceptions import InvalidRequestError  # noqa: E402
from backend.dto.user_dto import UserDTO, UserPageDTO  # noqa: E402
from backend.dto.validation_dto import ValidationDTO  # noqa: E402

ADMIN = UserDTO(id="a1", username="admin", full_name="System Administrator", role="admin", email="admin@example.com")
USERS = [ADMIN] + [
    UserDTO(id=f"u{i}", username=f"user{i}", full_name=f"Test User{chr(65 + i)}", role="user", email=f"u{i}@example.com")
    for i in range(30)
]


class FakeAdminFacade:
    def __init__(self):
        self.users = {u.id: u for u in USERS}
        self.calls = []

    def get_current_user(self):
        return ADMIN

    def list_users(self, skip=0, limit=50):
        items = list(self.users.values())
        return UserPageDTO(total=len(items), items=items[skip:skip + limit], skip=skip, limit=limit)

    def get_user(self, user_id):
        self.calls.append(("get", user_id))
        return self.users[user_id]

    def set_user_role(self, user_id, role):
        if user_id == ADMIN.id:
            raise InvalidRequestError("You cannot change your own role", 400)
        self.calls.append(("role", user_id, role))
        self.users[user_id] = dataclasses.replace(self.users[user_id], role=role)
        return self.users[user_id]

    def set_user_active(self, user_id, is_active):
        self.calls.append(("status", user_id, is_active))
        self.users[user_id] = dataclasses.replace(self.users[user_id], is_active=is_active)
        return self.users[user_id]

    def get_profile_photo(self, user_id=None):
        return None  # no photos on this computer

    def delete_user(self, user_id):
        self.calls.append(("delete", user_id))
        return self.users.pop(user_id, None) is not None

    def find_user_by_email(self, email):
        self.calls.append(("find", email))
        return next((u for u in self.users.values() if u.email == email), None)

    def update_user(self, user):
        self.calls.append(("update", user.id))
        self.users[user.id] = user
        return ValidationDTO(message=f"{user.full_name}'s details were saved.")


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def dialog():
    app = QApplication.instance() or QApplication([])
    from frontend.theme import apply_theme
    from frontend.views.user_admin_view import PAGE_SIZE, UserAdminDialog

    apply_theme(app)
    facade = FakeAdminFacade()
    dlg = UserAdminDialog(facade)
    dlg.show()
    assert wait_until(lambda: dlg.table.rowCount() == PAGE_SIZE)
    yield dlg, facade
    dlg.close()
    dlg.deleteLater()


def test_lists_first_page_and_pages_forward(dialog):
    dlg, _ = dialog
    assert "31 registered users" in dlg.count.text()
    assert dlg.page_label.text() == "Page 1 of 2"
    assert not dlg.prev_button.isEnabled() and dlg.next_button.isEnabled()
    dlg.next_button.click()
    assert wait_until(lambda: dlg.page_label.text() == "Page 2 of 2")
    assert dlg.table.rowCount() == 6


def test_own_account_cannot_be_changed(dialog):
    dlg, _ = dialog
    dlg.table.selectRow(0)  # the admin themself
    assert wait_until(lambda: dlg.details.name.text() == "System Administrator")
    for action in (dlg.details.apply_role, dlg.details.toggle_status, dlg.details.edit_details,
                   dlg.details.reset_password, dlg.details.delete_account):
        assert action.isHidden()
    assert not dlg.details.self_note.isHidden()


def test_change_role_and_disable(dialog):
    dlg, facade = dialog
    dlg.table.selectRow(1)
    assert wait_until(lambda: ("get", "u0") in facade.calls)
    dlg.details.role.setCurrentIndex(1)  # Administrator
    dlg.details.apply_role.click()
    assert wait_until(lambda: ("role", "u0", "admin") in facade.calls)
    assert wait_until(lambda: dlg.table.item(1, 3).text() == "Administrator")

    dlg.details.toggle_status.click()
    assert wait_until(lambda: ("status", "u0", False) in facade.calls)
    assert wait_until(lambda: dlg.table.item(1, 4).text() == "Disabled")
    assert dlg.details.toggle_status.text() == "Enable account"


def test_filter_hides_non_matching_rows(dialog):
    dlg, _ = dialog
    dlg.search.setText("userB")
    visible = [r for r in range(dlg.table.rowCount()) if not dlg.table.isRowHidden(r)]
    assert [dlg.table.item(r, 1).text() for r in visible] == ["user1"]



# ------------------------------------------------------------- manage accounts
class AcceptedDialog:
    """Stands in for a dialog the admin fills in and confirms."""

    def __init__(self, facade, user=None, *args, **kwargs):
        self.facade, self.user = facade, user
        self.result_message = "Done."
        self.session_expired = type("Signal", (), {"connect": lambda *_: None})()

    def exec(self):
        from PyQt6.QtWidgets import QDialog

        if self.user is not None:
            self.facade.update_user(dataclasses.replace(self.user, full_name="Renamed Person"))
        return QDialog.DialogCode.Accepted


def test_admin_edits_someones_details(dialog, monkeypatch):
    import frontend.views.user_admin_view as view

    dlg, facade = dialog
    monkeypatch.setattr(view, "EditDetailsDialog", AcceptedDialog)
    dlg.table.selectRow(1)
    assert wait_until(lambda: dlg.details.name.text() == USERS[1].full_name)
    dlg.details.edit_details.click()
    assert wait_until(lambda: dlg.table.item(1, 0).text() == "Renamed Person")
    assert ("update", "u0") in facade.calls and dlg.details.banner.text() == "Done."


def test_admin_deletes_an_account_after_confirming(dialog):
    dlg, facade = dialog
    dlg.table.selectRow(2)
    assert wait_until(lambda: dlg.details.name.text() == USERS[2].full_name)
    dlg.details.confirm_delete = lambda user: False
    dlg.details.delete_account.click()
    assert ("delete", "u1") not in facade.calls  # cancelled
    dlg.details.confirm_delete = lambda user: True
    dlg.details.delete_account.click()
    assert wait_until(lambda: "30 registered users" in dlg.count.text())
    assert ("delete", "u1") in facade.calls and "was deleted" in dlg.banner.text()


def test_enter_on_an_email_finds_the_user_among_all_users(dialog):
    dlg, facade = dialog
    dlg.search.setText("u29@example.com")  # on the second page
    dlg.search.returnPressed.emit()
    assert wait_until(lambda: dlg.details.name.text() == USERS[30].full_name)
    dlg.search.setText("nobody@example.com")
    dlg.search.returnPressed.emit()
    assert wait_until(lambda: "No user has the email address nobody@example.com" in dlg.banner.text())


def test_add_user_reloads_from_the_first_page(dialog, monkeypatch):
    import frontend.views.user_admin_view as view

    dlg, _ = dialog
    monkeypatch.setattr(view, "CreateUserDialog", lambda facade, parent: AcceptedDialog(facade))
    dlg.next_button.click()
    assert wait_until(lambda: dlg.page_label.text() == "Page 2 of 2")
    dlg.add_user.click()
    assert wait_until(lambda: dlg.page_label.text() == "Page 1 of 2")
    assert dlg.banner.text() == "Done."
