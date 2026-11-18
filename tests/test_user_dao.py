"""UserDAO: accounts through the auth server (faked), profile photos in a folder on this computer."""

import pytest

from backend.auth_exceptions import NotFoundError, SessionExpiredError
from backend.data.auth_session import AuthSession
from backend.data.dao.user_dao import UserDAO
from backend.data.session_store import MemorySessionStore
from backend.dto.user_dto import NewUserDTO, UserDTO

USER = {"id": "u1", "username": "ayesha", "full_name": "Ayesha Khan", "role": "user", "is_active": True,
        "email": "ayesha@example.com", "phone_number": "+923001234567"}


class FakeApi:
    def __init__(self):
        self.calls = []
        self.users = {"u1": dict(USER)}
        self.reject = set()  # access tokens the server refuses

    def _check(self, token):
        if token in self.reject:
            raise SessionExpiredError("Token has expired", 401)

    def refresh(self, refresh_token):
        self.calls.append(("refresh",))
        return {"access_token": "access2", "refresh_token": "refresh2", "expires_in": 1800}

    def update_user(self, token, user_id, fields):
        self._check(token)
        self.calls.append(("update", token, user_id, fields))
        self.users[user_id].update(fields)
        return self.users[user_id]

    def get_user(self, token, user_id):
        self._check(token)
        if user_id not in self.users:
            raise NotFoundError("User not found", 404)
        return self.users[user_id]

    def find_user_by_email(self, token, email):
        for user in self.users.values():
            if user["email"] == email:
                return user
        raise NotFoundError("No user has this email address", 404)

    def list_users(self, token, skip, limit):
        items = list(self.users.values())
        return {"total": len(items), "items": items[skip:skip + limit]}

    def delete_user(self, token, user_id):
        if self.users.pop(user_id, None) is None:
            raise NotFoundError("User not found", 404)

    def create_user(self, token, payload):
        self.calls.append(("create", payload))
        user = {"id": "u9", **{k: v for k, v in payload.items() if k != "password"}}
        self.users["u9"] = user
        return user

    def change_password(self, token, user_id, new_password, current_password=None):
        self.calls.append(("password", user_id, new_password, current_password))
        return {"message": "Password changed"}


@pytest.fixture
def dao(tmp_path):
    api = FakeApi()
    session = AuthSession(api, MemorySessionStore(), clock=lambda: 0.0)
    session.start({"access_token": "access1", "refresh_token": "refresh1", "expires_in": 1800}, remember=False)
    return UserDAO(api, session, tmp_path / "photos"), api


def test_save_sends_the_user_and_returns_it_as_stored(dao):
    users, api = dao
    saved = users.save(UserDTO.from_api({**USER, "full_name": "Ayesha K. Khan"}))
    assert saved.full_name == "Ayesha K. Khan"
    _, token, user_id, fields = api.calls[-1]
    assert (token, user_id) == ("access1", "u1")
    assert fields == {"full_name": "Ayesha K. Khan", "username": "ayesha", "email": "ayesha@example.com",
                      "phone_number": "+923001234567", "role": "user", "is_active": True}


def test_save_without_a_phone_does_not_send_one(dao):
    users, api = dao
    users.save(UserDTO.from_api({**USER, "phone_number": None}))
    assert "phone_number" not in api.calls[-1][3]


def test_a_rejected_token_is_renewed_once(dao):
    users, api = dao
    api.reject.add("access1")
    users.save(UserDTO.from_api(USER))
    assert ("refresh",) in api.calls and api.calls[-1][1] == "access2"


def test_find_by_id_and_email_return_none_when_missing(dao):
    users, _ = dao
    assert users.find_by_id("u1").username == "ayesha"
    assert users.find_by_id("nobody") is None
    assert users.find_by_email("ayesha@example.com").id == "u1"
    assert users.find_by_email("nobody@example.com") is None


def test_find_all_returns_a_page(dao):
    users, _ = dao
    page = users.find_all(0, 10)
    assert page.total == 1 and page.items[0].id == "u1" and page.limit == 10


def test_create_sends_the_password_and_role(dao):
    users, api = dao
    created = users.create(NewUserDTO("Carol New", "carol@example.com", "+923003333333", "carol", "Secret123", "admin"))
    assert created.id == "u9" and created.role == "admin"
    assert api.calls[-1][1]["password"] == "Secret123"


def test_change_password(dao):
    users, api = dao
    assert users.change_password("u1", "NewPass123", "OldPass123")
    assert api.calls[-1] == ("password", "u1", "NewPass123", "OldPass123")


# ------------------------------------------------------------- photos
def test_photo_is_kept_replaced_and_removed_on_this_computer(dao, tmp_path):
    users, _ = dao
    assert users.find_photo("u1") is None
    assert users.save_photo("u1", b"\x89PNG first")
    assert users.save_photo("u1", b"\x89PNG second")
    assert users.find_photo("u1") == b"\x89PNG second"
    assert [p.name for p in (tmp_path / "photos").iterdir()] == ["u1.img"]  # no leftover temporary file
    assert users.delete_photo("u1")
    assert users.find_photo("u1") is None and not users.delete_photo("u1")


def test_photos_are_kept_per_user(dao):
    users, _ = dao
    users.save_photo("u1", b"one")
    users.save_photo("u2", b"two")
    assert (users.find_photo("u1"), users.find_photo("u2")) == (b"one", b"two")


def test_a_user_id_cannot_reach_outside_the_photo_folder(dao, tmp_path):
    users, _ = dao
    users.save_photo("../../evil", b"x")
    assert not (tmp_path / "evil.img").exists()
    assert len(list((tmp_path / "photos").iterdir())) == 1


def test_deleting_a_user_removes_their_photo(dao):
    users, _ = dao
    users.save_photo("u1", b"photo")
    assert users.delete("u1")
    assert users.find_photo("u1") is None
    assert not users.delete("u1")  # already gone


# ------------------------------------------------------------- through the DataFacade
def test_data_facade_hands_user_operations_to_the_dao(dao):
    from backend.data.data_facade import DataFacade

    users, _ = dao
    facade = DataFacade(gemini_client=None, user_dao=users)
    assert facade.find_user_by_id("u1").username == "ayesha"
    assert facade.find_users().total == 1
    assert facade.save_profile_photo("u1", b"img") and facade.find_profile_photo("u1") == b"img"
    assert facade.delete_profile_photo("u1") and facade.find_profile_photo("u1") is None


def test_data_facade_without_a_user_dao_says_so():
    from backend.auth_exceptions import AuthError
    from backend.data.data_facade import DataFacade

    with pytest.raises(AuthError, match="not set up"):
        DataFacade(gemini_client=None).find_users()
