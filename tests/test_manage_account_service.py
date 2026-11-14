"""UserService's account management: editing details, passwords, profile photos and admin actions.

The server is replaced by an in-memory fake; requests go UserService -> DataFacade -> UserDAO -> fake.
"""

import dataclasses

import pytest

from backend.auth_exceptions import (
    ConflictError,
    FieldValidationError,
    InvalidRequestError,
    PermissionDeniedError,
    SessionExpiredError,
)
from backend.business.user import UserService
from backend.data.auth_session import AuthSession
from backend.data.dao.user_dao import UserDAO
from backend.data.data_facade import DataFacade
from backend.data.session_store import MemorySessionStore
from backend.dto.user_dto import NewUserDTO

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ME = {"id": "u1", "username": "ayesha", "full_name": "Ayesha Khan", "role": "user", "is_active": True,
      "email": "ayesha@example.com", "phone_number": "+923001234567", "email_verified": True}
ADMIN = {"id": "a1", "username": "admin", "full_name": "System Administrator", "role": "admin", "is_active": True,
         "email": "admin@example.com", "phone_number": "+10000000000", "email_verified": True}
OTHER = {"id": "u2", "username": "bilal", "full_name": "Bilal Ahmed", "role": "user", "is_active": True,
         "email": "bilal@example.com", "phone_number": "+923002222222", "email_verified": True}


class FakeServer:
    """Just enough of the auth server: it stores what it is sent and enforces unique usernames."""

    def __init__(self, signed_in: dict):
        self.signed_in = signed_in
        self.users = {u["id"]: dict(u) for u in (ME, ADMIN, OTHER)}
        self.calls = []

    def login(self, username, password):
        return {"access_token": "access1", "refresh_token": "refresh1", "expires_in": 1800,
                "user": self.users[self.signed_in["id"]]}

    def get_user(self, token, user_id):
        return self.users[user_id]

    def update_user(self, token, user_id, fields):
        self.calls.append(("update", user_id, fields))
        taken = {u["username"] for uid, u in self.users.items() if uid != user_id}
        if fields.get("username") in taken:
            raise ConflictError("Username is already taken", "username")
        self.users[user_id].update(fields)
        return self.users[user_id]

    def change_password(self, token, user_id, new_password, current_password=None):
        self.calls.append(("password", user_id, new_password, current_password))
        if current_password == "wrong":
            raise FieldValidationError("Current password is incorrect",
                                       {"current_password": "Current password is incorrect"})
        return {"message": "Password changed"}

    def create_user(self, token, payload):
        self.calls.append(("create", payload))
        if payload["username"] in {u["username"] for u in self.users.values()}:
            raise ConflictError("Username is already taken", "username")
        user = {"id": "u9", **{k: v for k, v in payload.items() if k != "password"}}
        self.users["u9"] = user
        return user

    def delete_user(self, token, user_id):
        self.calls.append(("delete", user_id))
        del self.users[user_id]

    def find_user_by_email(self, token, email):
        from backend.auth_exceptions import NotFoundError

        for user in self.users.values():
            if user["email"] == email:
                return user
        raise NotFoundError("No user has this email address", 404)


def _signed_in(tmp_path, who: dict):
    server, store = FakeServer(who), MemorySessionStore()
    session = AuthSession(server, store, clock=lambda: 0.0)
    facade = DataFacade(gemini_client=None, user_dao=UserDAO(server, session, tmp_path / "photos"))
    service = UserService(server, store, clock=lambda: 0.0, session=session, data_facade=facade)
    service.log_in(who["username"], "Password123")
    return service, server


@pytest.fixture
def user(tmp_path):
    return _signed_in(tmp_path, ME)


@pytest.fixture
def admin(tmp_path):
    return _signed_in(tmp_path, ADMIN)


def _edit(service, **changes):
    return dataclasses.replace(service.current_user, **changes)


# ------------------------------------------------------------- your own details
def test_user_saves_tidied_details_and_sees_them_at_once(user):
    service, server = user
    result = service.update_user(_edit(service, full_name="  Ayesha   Kiran Khan ", username=" Ayesha.K ",
                                       phone_number="+92 300 765 4321"))
    assert result.is_valid and result.message == "Your details were saved."
    assert server.calls[-1][2]["full_name"] == "Ayesha Kiran Khan"
    me = service.current_user
    assert (me.username, me.phone_number) == ("ayesha.k", "+923007654321")


def test_invalid_details_are_reported_per_field_and_not_sent(user):
    service, server = user
    result = service.update_user(_edit(service, full_name="A1", username="a", phone_number="0300"))
    assert not result.is_valid
    assert set(result.errors) == {"full_name", "username", "phone_number"}
    assert server.calls == []


def test_a_taken_username_comes_back_as_a_field_error(user):
    service, _ = user
    result = service.update_user(_edit(service, username="bilal"))
    assert result.errors == {"username": "Username is already taken"}
    assert service.current_user.username == "ayesha"  # unchanged


@pytest.mark.parametrize(("change", "field"), [
    ({"email": "new@example.com"}, "email"),
    ({"role": "admin"}, "role"),
    ({"is_active": False}, "is_active"),
])
def test_a_user_cannot_change_their_own_email_role_or_status(user, change, field):
    service, server = user
    result = service.update_user(_edit(service, **change))
    assert field in result.errors and server.calls == []


def test_a_user_cannot_edit_someone_else(user):
    service, _ = user
    with pytest.raises(PermissionDeniedError):
        service.update_user(dataclasses.replace(service.get_user("u2"), full_name="Changed Name"))


# ------------------------------------------------------------- admin editing others
def test_admin_changes_someones_email_role_and_status(admin):
    service, server = admin
    bilal = service.get_user("u2")
    result = service.update_user(dataclasses.replace(bilal, email=" Bilal2@Example.com ", role="admin",
                                                     is_active=False))
    assert result.is_valid and "verification link was sent to bilal2@example.com" in result.message
    assert server.users["u2"]["email"] == "bilal2@example.com"
    assert server.users["u2"]["role"] == "admin" and server.users["u2"]["is_active"] is False
    assert service.current_user.id == "a1"  # still signed in as the admin


def test_admin_cannot_change_a_google_accounts_email(admin):
    service, server = admin
    server.users["u2"]["auth_provider"] = "google"
    result = service.update_user(dataclasses.replace(service.get_user("u2"), email="x@example.com"))
    assert "email" in result.errors


def test_role_and_status_shortcuts_save_through_the_dao(admin):
    service, server = admin
    assert service.set_user_role("u2", "admin").role == "admin"
    assert service.set_user_active("u2", False).is_active is False
    assert [call[0] for call in server.calls] == ["update", "update"]


# ------------------------------------------------------------- passwords
def test_changing_your_password_needs_the_current_one(user):
    service, server = user
    result = service.change_password("u1", "NewPass123", "NewPass123")
    assert result.errors == {"current_password": "Enter your current password"} and server.calls == []
    result = service.change_password("u1", "NewPass123", "NewPass123", current_password="Password123")
    assert result.is_valid and result.message == "Your password was changed."
    assert server.calls[-1] == ("password", "u1", "NewPass123", "Password123")


def test_password_mistakes_are_field_errors(user):
    service, _ = user
    assert "new_password" in service.change_password("u1", "short", "short", "Password123").errors
    assert service.change_password("u1", "NewPass123", "Different1", "Password123").errors == {
        "confirm_password": "Passwords do not match"}
    assert service.change_password("u1", "NewPass123", "NewPass123", "wrong").errors == {
        "current_password": "Current password is incorrect"}


def test_google_users_have_no_password_to_change(user):
    service, server = user
    service._user = dataclasses.replace(service.current_user, auth_provider="google")
    result = service.change_password("u1", "NewPass123", "NewPass123", "x")
    assert "form" in result.errors and server.calls == []


def test_admin_resets_someone_elses_password_without_the_current_one(admin):
    service, server = admin
    result = service.change_password("u2", "Reset12345", "Reset12345", current_password="ignored")
    assert result.is_valid and server.calls[-1] == ("password", "u2", "Reset12345", None)


def test_a_user_cannot_reset_someone_elses_password(user):
    service, _ = user
    with pytest.raises(PermissionDeniedError):
        service.change_password("u2", "NewPass123", "NewPass123")


# ------------------------------------------------------------- profile photo (this computer only)
def test_photo_is_saved_locally_and_removed(user, tmp_path):
    service, server = user
    image = tmp_path / "me.png"
    image.write_bytes(PNG)
    result = service.set_profile_photo(str(image))
    assert result.is_valid and "this computer only" in result.message
    assert service.get_profile_photo() == PNG and service.get_profile_photo("u1") == PNG
    assert (tmp_path / "photos" / "u1.img").read_bytes() == PNG
    assert server.calls == []  # nothing was sent to the server
    assert service.remove_profile_photo() and service.get_profile_photo() is None
    assert not service.remove_profile_photo()


def test_photo_that_is_not_an_image_is_refused(user, tmp_path):
    service, _ = user
    text = tmp_path / "notes.png"
    text.write_text("hello")
    assert "not a supported image" in service.set_profile_photo(str(text)).errors["photo"]
    assert service.get_profile_photo() is None


def test_photo_that_is_too_big_or_missing_is_refused(user, tmp_path, monkeypatch):
    service, _ = user
    import backend.business.user.user_service as module

    big = tmp_path / "big.png"
    big.write_bytes(PNG + b"\x00" * 100)
    monkeypatch.setattr(module, "MAX_PHOTO_BYTES", 50)
    assert "smaller than" in service.set_profile_photo(str(big)).errors["photo"]
    assert "could not be read" in service.set_profile_photo(str(tmp_path / "missing.png")).errors["photo"]


@pytest.mark.parametrize("header", [b"\xff\xd8\xff\xe0", b"GIF89a", b"BM", b"RIFF\x00\x00\x00\x00WEBP"])
def test_other_image_formats_are_accepted(user, tmp_path, header):
    service, _ = user
    image = tmp_path / "photo"
    image.write_bytes(header + b"\x00" * 16)
    assert service.set_profile_photo(str(image)).is_valid


def test_no_photo_when_signed_out(user):
    service, _ = user
    service.log_out()
    assert service.get_profile_photo() is None
    with pytest.raises(SessionExpiredError):
        service.remove_profile_photo()


# ------------------------------------------------------------- admin: create, find, delete
NEW = NewUserDTO(full_name="Carol  New", email=" Carol@Example.com", phone_number="+92 300 3333333",
                 username="Carol", password="CarolPass1", role="user")


def test_admin_creates_a_user_with_tidied_values(admin):
    service, server = admin
    result = service.create_user(NEW)
    assert result.is_valid and "Account created for carol" in result.message
    sent = server.calls[-1][1]
    assert sent == {"full_name": "Carol New", "email": "carol@example.com", "phone_number": "+923003333333",
                    "username": "carol", "password": "CarolPass1", "role": "user"}


def test_creating_a_user_reports_bad_and_taken_fields(admin):
    service, server = admin
    bad = service.create_user(dataclasses.replace(NEW, email="nope", password="short", role="boss"))
    assert set(bad.errors) == {"email", "password", "role"} and server.calls == []
    taken = service.create_user(dataclasses.replace(NEW, username="bilal"))
    assert taken.errors == {"username": "Username is already taken"}


def test_only_admins_create_or_delete_users(user):
    service, _ = user
    with pytest.raises(PermissionDeniedError):
        service.create_user(NEW)
    with pytest.raises(PermissionDeniedError):
        service.delete_user("u2")


def test_admin_deletes_someone_but_not_themself(admin, tmp_path):
    service, server = admin
    UserDAO(server, None, tmp_path / "photos").save_photo("u2", PNG)
    assert service.delete_user("u2")
    assert "u2" not in server.users and not (tmp_path / "photos" / "u2.img").exists()
    with pytest.raises(InvalidRequestError):
        service.delete_user("a1")


def test_admin_finds_a_user_by_email(admin):
    service, _ = admin
    assert service.find_user_by_email("  BILAL@example.com ").id == "u2"
    assert service.find_user_by_email("nobody@example.com") is None
    assert service.find_user_by_email("   ") is None
