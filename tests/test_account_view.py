"""The account card and the sign-up details dialog (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.facade import IBusinessFacade  # noqa: E402
from backend.dto.user_dto import UserDTO  # noqa: E402
from frontend.views.account_view import AccountView, SignupDetailsDialog, format_date  # noqa: E402

SIGNED_UP = datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _user(**extra) -> UserDTO:
    values = dict(id="1", username="ayesha", full_name="Ayesha Khan", role="user", email="ayesha@example.com",
                  email_verified=True, phone_number="+923001234567", auth_provider="local", created_at=SIGNED_UP)
    values.update(extra)
    return UserDTO(**values)


def test_signup_details_show_what_the_user_signed_up_with(app):
    dialog = SignupDetailsDialog(_user())
    shown = {key: label.text() for key, label in dialog.values.items()}

    assert shown == {
        "full_name": "Ayesha Khan",
        "username": "ayesha",
        "email": "ayesha@example.com  ✓ verified",
        "phone": "+923001234567",
        "provider": "Username and password",
        "created": format_date(SIGNED_UP),
    }
    dialog.deleteLater()


def test_signup_details_for_a_google_account_without_a_phone(app):
    dialog = SignupDetailsDialog(_user(auth_provider="google", phone_number=None, email_verified=False))

    assert dialog.values["provider"].text() == "Google"
    assert dialog.values["phone"].text() == "—"
    assert dialog.values["email"].text() == "ayesha@example.com  (not verified)"
    dialog.deleteLater()


def test_account_card_shows_the_same_details(app):
    card = AccountView(MagicMock(spec=IBusinessFacade))
    card.set_user(_user())

    assert card._values["email"].text() == "ayesha@example.com  ✓ verified"
    assert card._values["provider"].text() == "Username and password"
    card.deleteLater()


def _png(width=40, height=20) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_avatar_shows_the_photo_in_a_circle(app):
    from frontend.views.account_view import Avatar, round_photo

    avatar = Avatar(48)
    avatar.set_user(_user(), _png())
    assert avatar.has_photo and avatar.text() == ""
    circle = round_photo(_png(), 48).toImage()
    assert circle.width() == circle.height() == 48
    assert circle.pixelColor(24, 24).red() == 255 and circle.pixelColor(0, 0).alpha() == 0  # corners cut away
    avatar.deleteLater()


def test_avatar_falls_back_to_initials(app):
    from frontend.views.account_view import Avatar

    avatar = Avatar(48)
    avatar.set_user(_user(), _png())
    avatar.set_user(_user(), None)  # photo removed
    assert not avatar.has_photo and avatar.text() == "AK"
    avatar.set_user(_user(), b"not an image")
    assert not avatar.has_photo and avatar.text() == "AK"
    avatar.deleteLater()


class PhotoFacade:
    """Keeps one photo in memory, like the DataFacade keeps it in a file."""

    def __init__(self, user):
        self.user, self.photo = user, None

    def get_current_user(self):
        return self.user

    def get_profile_photo(self, user_id=None):
        return self.photo

    def set_profile_photo(self, path):
        from backend.dto.validation_dto import ValidationDTO

        data = open(path, "rb").read()
        if not data.startswith(b"\x89PNG"):
            result = ValidationDTO()
            result.add_error("photo", "This file is not a supported image.")
            return result
        self.photo = data
        return ValidationDTO(message="Your photo was updated. It is kept on this computer only.")

    def remove_profile_photo(self):
        self.photo = None
        return True


def _wait(condition, timeout=5.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_choosing_and_removing_a_photo_updates_the_page(app, tmp_path):
    facade = PhotoFacade(_user())
    card = AccountView(facade)
    card.set_user(_user())
    assert not card.avatar.has_photo and card.change_photo.text() == "Add photo" and card.remove_photo.isHidden()
    changed = []
    card.user_changed.connect(changed.append)

    image = tmp_path / "me.png"
    image.write_bytes(_png())
    card.choose_photo_file = lambda: str(image)
    card.choose_photo()
    assert _wait(lambda: card.avatar.has_photo)
    assert not card.remove_photo.isHidden() and "this computer only" in card.banner.text() and changed

    card.delete_photo()
    assert _wait(lambda: not card.avatar.has_photo)
    assert card.remove_photo.isHidden() and card.banner.text() == "Your photo was removed."
    card.deleteLater()


def test_a_file_that_is_not_an_image_is_refused(app, tmp_path):
    card = AccountView(PhotoFacade(_user()))
    card.set_user(_user())
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    card.choose_photo_file = lambda: str(text)
    card.choose_photo()
    assert _wait(lambda: card.banner.text() == "This file is not a supported image.")
    assert not card.avatar.has_photo
    card.deleteLater()


def test_google_accounts_have_no_password_to_change(app):
    card = AccountView(PhotoFacade(_user()))
    card.set_user(_user(auth_provider="google"))
    assert not card.change_password.isEnabled()
    card.set_user(_user())
    assert card.change_password.isEnabled()
    card.deleteLater()
