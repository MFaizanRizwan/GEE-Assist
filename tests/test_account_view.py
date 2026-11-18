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


class AccountFacade:
    """The signed-in user, their photo in memory, and saves that behave like the real service."""

    def __init__(self, user):
        self.user, self.photo, self.calls = user, None, []

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

    def update_user(self, user):
        import dataclasses

        from backend.dto.validation_dto import ValidationDTO

        self.calls.append(("update", user))
        result = ValidationDTO()
        if user.username == "taken":
            result.add_error("username", "Username is already taken")
            return result
        self.user = dataclasses.replace(user, full_name=" ".join(user.full_name.split()))  # tidied, as the server does
        result.message = "Your details were saved."
        return result

    def change_password(self, user_id, new, confirm, current=None):
        from backend.dto.validation_dto import ValidationDTO

        self.calls.append(("password", user_id, new, confirm, current))
        result = ValidationDTO()
        if current != "OldPass123":
            result.add_error("current_password", "Current password is incorrect")
            return result
        result.message = "Your password was changed."
        return result


def _wait(condition, timeout=5.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def page(app):
    facade = AccountFacade(_user())
    card = AccountView(facade)
    card.set_user(_user())
    card.show()
    yield card, facade
    card.close()
    card.deleteLater()


def _type(editor, text):
    editor.display.click()
    editor.input.setText(text)
    editor.input.textEdited.emit(text)


# ------------------------------------------------------------- look
def test_details_on_the_left_and_photo_with_greeting_on_the_right(page):
    card, _ = page
    assert card.editors["full_name"].display.text() == "Ayesha Khan"
    assert card.editors["phone_number"].display.text() == "+923001234567"
    assert card._values["role"].text() == "User" and card.greeting.text() == "Welcome, Ayesha!"
    from PyQt6.QtCore import QPoint

    photo_left = card.photo.mapTo(card, QPoint(0, 0)).x()
    name_right = card.editors["full_name"].mapTo(card, QPoint(card.editors["full_name"].width(), 0)).x()
    assert photo_left > name_right  # the photo is to the right of the details
    assert card.save_bar.isHidden()  # nothing changed yet


# ------------------------------------------------------------- click to edit, Save / Discard
def test_clicking_the_name_without_changing_it_shows_no_save_buttons(page):
    card, _ = page
    card.editors["full_name"].display.click()
    assert card.editors["full_name"].is_editing() and card.save_bar.isHidden()


def test_changing_the_name_shows_save_and_discard_bottom_right(page):
    card, _ = page
    _type(card.editors["full_name"], "Ayesha Kiran Khan")
    assert not card.save_bar.isHidden()
    assert card.save_button.x() > card.discard_button.x() > card.width() // 2
    _type(card.editors["full_name"], "Ayesha Khan")  # typed back to what it was
    assert card.save_bar.isHidden()


def test_saving_a_new_name_updates_the_page_and_the_window(page):
    card, facade = page
    changed = []
    card.user_changed.connect(changed.append)
    _type(card.editors["full_name"], "Ayesha   Kiran Khan")
    card.save_button.click()
    assert _wait(lambda: changed)
    assert facade.calls[0][1].full_name == "Ayesha   Kiran Khan"
    assert card.editors["full_name"].display.text() == "Ayesha Kiran Khan"  # the tidied, saved value
    assert not card.editors["full_name"].is_editing() and card.save_bar.isHidden()
    assert card.banner.text() == "Your details were saved." and changed[0].full_name == "Ayesha Kiran Khan"


def test_a_taken_username_shows_under_the_username(page):
    card, _ = page
    _type(card.editors["username"], "taken")
    card.save_button.click()
    assert _wait(lambda: not card.editors["username"].error.isHidden())
    assert card.editors["username"].error.text() == "Username is already taken"
    assert not card.save_bar.isHidden()  # still unsaved


def test_discard_puts_everything_back(page):
    card, facade = page
    _type(card.editors["full_name"], "Someone Else")
    card.password_fields["new_password"].set_text("NewPass123")
    card.discard_button.click()
    assert card.editors["full_name"].display.text() == "Ayesha Khan" and not card.editors["full_name"].is_editing()
    assert card.password_fields["new_password"].text() == "" and card.save_bar.isHidden()
    assert facade.calls == []


# ------------------------------------------------------------- password
def test_password_is_changed_with_the_current_one_and_the_new_one_twice(page):
    card, facade = page
    for key, value in (("current_password", "OldPass123"), ("new_password", "NewPass123"),
                       ("confirm_password", "NewPass123")):
        card.password_fields[key].set_text(value)
        card.password_fields[key].input.textEdited.emit(value)
    assert not card.save_bar.isHidden()
    card.save_button.click()
    assert _wait(lambda: card.banner.text() == "Your password was changed.")
    assert facade.calls == [("password", "1", "NewPass123", "NewPass123", "OldPass123")]
    assert all(field.text() == "" for field in card.password_fields.values()) and card.save_bar.isHidden()


def test_a_wrong_current_password_shows_under_its_field(page):
    card, _ = page
    card.password_fields["current_password"].set_text("wrong")
    card.password_fields["new_password"].set_text("NewPass123")
    card.password_fields["confirm_password"].set_text("NewPass123")
    card.save()
    assert _wait(lambda: card.password_fields["current_password"].has_error())
    assert card.password_fields["new_password"].text() == "NewPass123"  # kept to try again


def test_google_accounts_have_no_password_section(app):
    card = AccountView(AccountFacade(_user()))
    card.set_user(_user(auth_provider="google"))
    assert not card.password_section.isVisibleTo(card)
    card.set_user(_user())
    assert card.password_section.isVisibleTo(card)
    card.deleteLater()


# ------------------------------------------------------------- photo
def test_clicking_the_photo_offers_change_or_remove(page, tmp_path):
    card, _ = page
    assert card.change_photo_action.text() == "Add photo…" and not card.remove_photo_action.isVisible()
    shown = []
    card.photo_menu.popup = lambda point: shown.append(point)
    card.photo.clicked.emit()
    assert shown

    image = tmp_path / "me.png"
    image.write_bytes(_png())
    card.choose_photo_file = lambda: str(image)
    card.change_photo_action.trigger()
    assert _wait(lambda: card.photo.has_photo)
    assert card.change_photo_action.text() == "Change photo…" and card.remove_photo_action.isVisible()
    assert "this computer only" in card.banner.text()

    card.remove_photo_action.trigger()
    assert _wait(lambda: not card.photo.has_photo)
    assert card.banner.text() == "Your photo was removed." and not card.remove_photo_action.isVisible()


def test_a_file_that_is_not_an_image_is_refused(page, tmp_path):
    card, _ = page
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    card.choose_photo_file = lambda: str(text)
    card.choose_photo()
    assert _wait(lambda: card.banner.text() == "This file is not a supported image.")
    assert not card.photo.has_photo


def test_hovering_the_photo_shows_no_tooltip(page):
    card, _ = page
    assert card.photo.toolTip() == ""  # the hint under the photo says to click it
    assert card.photo.accessibleName() == "Your photo: click to change or remove it"


def test_the_avatar_style_stays_on_the_avatar(app):
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QLabel

    from frontend import theme
    from frontend.views.account_view import Avatar

    avatar = Avatar(96)
    avatar.set_user(_user(), None)
    avatar.show()
    QApplication.processEvents()
    image = avatar.grab().toImage()
    middle = QColor(image.pixel(10, 48))  # inside the circle, left of the initials
    assert middle.saturation() > 60  # still the green-blue gradient
    assert avatar.styleSheet().startswith("QLabel#Avatar {")

    inner = QLabel("hint", avatar)  # e.g. a tooltip or any label shown from the avatar
    inner.show()
    QApplication.processEvents()
    assert inner.font().pointSize() != max(9, 96 // 4)  # not the avatar's large initials font
    assert QColor(inner.grab().toImage().pixel(1, 1)) != QColor(theme.LEAF)
    avatar.deleteLater()
