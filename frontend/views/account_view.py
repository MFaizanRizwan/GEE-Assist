"""The signed-in user's account page (details, password, profile photo) and the sign-up details dialog."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.auth_exceptions import AuthError, SessionExpiredError
from backend.business.facade import IBusinessFacade
from backend.dto.user_dto import UserDTO
from backend.dto.validation_dto import ValidationDTO
from frontend import theme
from frontend.views.account_dialogs import PASSWORD_HINT
from frontend.widgets.form_widgets import Banner, BusyButton, PasswordField, add_soft_shadow
from frontend.widgets.inline_edit import InlineEdit
from frontend.workers.task_worker import run_task

_PROVIDERS = {"local": "Username and password", "google": "Google"}


def format_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%d %b %Y, %H:%M")


def format_email(user: UserDTO) -> str:
    if not user.email:
        return "—"
    return user.email + ("  ✓ verified" if user.email_verified else "  (not verified)")


def format_provider(user: UserDTO) -> str:
    return _PROVIDERS.get(user.auth_provider, user.auth_provider.title())


def round_photo(image: bytes, size: int, pixel_ratio: float = 1.0) -> QPixmap | None:
    """``image`` cropped to its centre square and cut into a circle ``size`` points wide; None if unreadable."""
    picture = QImage.fromData(image)
    if picture.isNull():
        return None
    side = min(picture.width(), picture.height())
    square = picture.copy((picture.width() - side) // 2, (picture.height() - side) // 2, side, side)
    pixels = max(1, round(size * pixel_ratio))
    square = square.scaled(pixels, pixels, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    result = QPixmap(pixels, pixels)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, pixels, pixels)
    painter.setClipPath(clip)
    painter.drawImage(0, 0, square)
    painter.end()
    result.setDevicePixelRatio(pixel_ratio)
    return result


class Avatar(QLabel):
    """The user's profile photo in a circle, or their initials when there is none."""

    def __init__(self, size: int = 64, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self.has_photo = False
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("Avatar")
        # Scoped to the avatar itself: unscoped, the circle style also applied to the avatar's tooltip,
        # drawing it as a huge gradient banner.
        self.setStyleSheet(
            f"QLabel#Avatar {{ border-radius: {size // 2}px; color: {theme.WHITE}; font-family: '{theme.SERIF}';"
            f"font-size: {max(9, size // 4)}pt;"
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {theme.LEAF}, stop:1 {theme.OCEAN}); }}"
        )

    def set_user(self, user: UserDTO, photo: bytes | None = None) -> None:
        pixmap = round_photo(photo, self._size, self.devicePixelRatioF()) if isinstance(photo, bytes) else None
        self.has_photo = pixmap is not None
        if pixmap is None:
            self.clear()
            self.setText(user.initials)
        else:
            self.setPixmap(pixmap)


class PhotoButton(Avatar):
    """The large profile photo; clicking it offers to change or remove the photo."""

    clicked = pyqtSignal()

    def __init__(self, size: int, parent: QWidget | None = None):
        super().__init__(size, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # No tooltip: the hint under the photo already says to click it (and a tooltip took on the
        # photo's large circle style). Screen readers still hear what it does.
        self.setAccessibleName("Your photo: click to change or remove it")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# (key, title, hint) of the details you can change by clicking them. Keys are UserDTO fields.
_EDITABLE = {
    "full_name": "Click to change your name",
    "phone_number": "Click to change your phone number",
}
_ROWS = (("full_name", "Full name"), ("username", "Username"), ("email", "Email"), ("phone_number", "Phone"),
         ("role", "Role"), ("provider", "Sign-in method"), ("created", "Member since"),
         ("last_login", "Last sign-in"))


class AccountView(QFrame):
    """The signed-in user's account: details on the left, photo on the right, password below.

    Clicking the name (or username, phone) makes it editable; once something really changed,
    Discard and Save changes appear at the bottom right. Saving also changes the password when
    its fields are filled in. Clicking the photo offers to change or remove it.
    """

    session_expired = pyqtSignal()
    user_changed = pyqtSignal(object)  # UserDTO, after details or the photo changed

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(parent)
        self._facade = facade
        self._user: UserDTO | None = None
        self._password: dict[str, str] = {}
        self._messages: list[str] = []
        self.setObjectName("AuthCard")
        self.setMaximumWidth(1180)
        add_soft_shadow(self)

        self.banner = Banner()

        # ---- details (left)
        self.editors: dict[str, InlineEdit] = {}
        self._values: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(4)
        grid.setColumnMinimumWidth(0, 140)
        for row, (key, title) in enumerate(_ROWS):
            label = QLabel(title, objectName="Muted")
            label.setMinimumHeight(38)
            grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            if key in _EDITABLE:
                editor = InlineEdit(hint=_EDITABLE[key])
                editor.changed.connect(self._update_save_bar)
                editor.submitted.connect(self.save)
                grid.addWidget(editor, row, 1)
                self.editors[key] = editor
            else:
                value = QLabel()
                value.setMinimumHeight(38)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value.setStyleSheet(f"color: {theme.INK}; padding-left: 5px;")  # lines up with the editors
                grid.addWidget(value, row, 1, Qt.AlignmentFlag.AlignTop)
                self._values[key] = value
        grid.setColumnStretch(1, 1)

        # ---- photo (right)
        self.photo = PhotoButton(184)
        self.greeting = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.greeting.setWordWrap(True)
        self.greeting.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 17pt; color: {theme.INK};")
        photo_hint = QLabel("Click the photo to change it", objectName="FieldHint",
                            alignment=Qt.AlignmentFlag.AlignCenter)
        self.photo_menu = QMenu(self)
        self.photo_menu.setStyleSheet(theme.MENU_STYLE)
        self.change_photo_action = self.photo_menu.addAction("Change photo…")
        self.remove_photo_action = self.photo_menu.addAction("Remove photo")
        photo_column = QVBoxLayout()
        photo_column.setSpacing(10)
        photo_column.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignHCenter)
        photo_column.addWidget(self.greeting)
        photo_column.addWidget(photo_hint)
        photo_column.addStretch(1)
        photo_box = QWidget()
        photo_box.setFixedWidth(260)
        photo_box.setLayout(photo_column)

        top = QHBoxLayout()
        top.setSpacing(48)
        top.addLayout(grid, 1)
        top.addWidget(photo_box, 0, Qt.AlignmentFlag.AlignTop)

        # ---- password (only for accounts that sign in with one)
        self.password_section = QWidget()
        heading = QLabel("Change password")
        heading.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 14pt; color: {theme.INK};")
        intro = QLabel("Type your current password, then the new one twice. It is changed when you save.",
                       objectName="Muted")
        intro.setWordWrap(True)
        self.password_fields = {
            "current_password": PasswordField("Current password", "Your current password"),
            "new_password": PasswordField("New password", "New password", PASSWORD_HINT),
            "confirm_password": PasswordField("Confirm new password", "Type the new password again"),
        }
        password_row = QHBoxLayout()
        password_row.setSpacing(16)
        for field in self.password_fields.values():
            field.input.textEdited.connect(self._update_save_bar)
            field.input.returnPressed.connect(self.save)
            password_row.addWidget(field, 1, Qt.AlignmentFlag.AlignTop)
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background: {theme.BORDER};")
        password_layout = QVBoxLayout(self.password_section)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(10)
        password_layout.addWidget(separator)
        password_layout.addSpacing(8)
        password_layout.addWidget(heading)
        password_layout.addWidget(intro)
        password_layout.addLayout(password_row)

        # ---- Discard / Save, bottom right, only while something is changed
        self.discard_button = QPushButton("Discard", objectName="SecondaryButton")
        self.discard_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.discard_button.setMinimumHeight(44)
        self.save_button = BusyButton("Save changes", "Saving…")
        self.save_bar = QWidget()
        bar = QHBoxLayout(self.save_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addStretch(1)
        bar.addWidget(self.discard_button)
        bar.addWidget(self.save_button)
        keep_place = self.save_bar.sizePolicy()
        keep_place.setRetainSizeWhenHidden(True)  # the page does not jump when the buttons appear
        self.save_bar.setSizePolicy(keep_place)
        self.save_bar.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 36, 44, 30)
        layout.setSpacing(20)
        layout.addWidget(self.banner)
        layout.addLayout(top)
        layout.addWidget(self.password_section)
        layout.addStretch(1)
        layout.addWidget(self.save_bar)

        self.photo.clicked.connect(self.show_photo_menu)
        self.change_photo_action.triggered.connect(self.choose_photo)
        self.remove_photo_action.triggered.connect(self.delete_photo)
        self.discard_button.clicked.connect(self.discard)
        self.save_button.clicked.connect(self.save)

    def set_user(self, user: UserDTO) -> None:
        """Show ``user``. A change being typed is kept."""
        self._user = user
        first_name = user.full_name.split()[0] if user.full_name.split() else user.username
        self.greeting.setText(f"Welcome, {first_name}!")
        self.photo.set_user(user, self._facade.get_profile_photo(user.id))
        self.change_photo_action.setText("Change photo…" if self.photo.has_photo else "Add photo…")
        self.remove_photo_action.setVisible(self.photo.has_photo)
        self.editors["full_name"].set_value(user.full_name)
        self.editors["phone_number"].set_value(user.phone_number)
        self._values["username"].setText(f"@{user.username}")
        self._values["username"].setToolTip("Username cannot be changed once set.")
        self._values["email"].setText(format_email(user))
        self._values["email"].setToolTip("Only an administrator can change your email address.")
        self._values["role"].setText("Administrator" if user.is_admin else "User")
        self._values["provider"].setText(format_provider(user))
        self._values["created"].setText(format_date(user.created_at))
        self._values["last_login"].setText(format_date(user.last_login_at))
        self.password_section.setVisible(user.auth_provider != "google")
        self._update_save_bar()

    # ------------------------------------------------------------- changes
    def has_changes(self) -> bool:
        typed_password = self.password_section.isVisibleTo(self) and any(
            field.text() for field in self.password_fields.values())
        return typed_password or any(editor.is_dirty() for editor in self.editors.values())

    def _update_save_bar(self) -> None:
        self.save_bar.setVisible(self.has_changes() or not self.save_button.isEnabled())

    def discard(self) -> None:
        for editor in self.editors.values():
            editor.discard()
        for field in self.password_fields.values():
            field.set_text("")
            field.clear_error()
        self.banner.clear()
        self._update_save_bar()

    def save(self) -> None:
        if self._user is None or not self.save_button.isEnabled() or not self.has_changes():
            return
        edits = {key: editor.value() for key, editor in self.editors.items() if editor.is_dirty()}
        self._password = ({key: field.text() for key, field in self.password_fields.items()}
                          if self.password_section.isVisibleTo(self) else {})
        self._messages = []
        self.banner.clear()
        self.save_button.set_busy(True)
        self.discard_button.setEnabled(False)
        if edits:
            run_task(self, self._facade.update_user, dataclasses.replace(self._user, **edits),
                     on_success=self._on_details_saved, on_error=self._on_save_error)
        else:
            self._save_password()

    def _on_details_saved(self, result: ValidationDTO) -> None:
        if not result.is_valid:
            self._show_errors(result.errors, self.editors)
            self._finish_saving()
            return
        user = self._facade.get_current_user() or self._user
        self.set_user(user)
        for editor in self.editors.values():
            editor.discard()  # back to plain text, showing the saved (tidied) value
        self._messages.append(result.message)
        self.user_changed.emit(user)
        self._save_password()

    def _save_password(self) -> None:
        if not any(self._password.values()):
            self._finish_saving()
            return
        for field in self.password_fields.values():
            field.clear_error()
        run_task(self, self._facade.change_password, self._user.id, self._password["new_password"],
                 self._password["confirm_password"], self._password["current_password"],
                 on_success=self._on_password_saved, on_error=self._on_save_error)

    def _on_password_saved(self, result: ValidationDTO) -> None:
        if result.is_valid:
            for field in self.password_fields.values():
                field.set_text("")
            self._messages.append(result.message)
        else:
            self._show_errors(result.errors, self.password_fields)
        self._finish_saving()

    def _show_errors(self, errors: dict[str, str], fields: dict) -> None:
        elsewhere = []
        for key, message in errors.items():
            if key in fields:
                fields[key].set_error(message)
            else:
                elsewhere.append(message)
        if elsewhere:
            self.banner.show_error(" ".join(elsewhere))

    def _finish_saving(self) -> None:
        self.save_button.set_busy(False)
        self.discard_button.setEnabled(True)
        if self._messages and not self.banner.isVisibleTo(self):
            self.banner.show_success(" ".join(self._messages))
        self._update_save_bar()

    def _on_save_error(self, exc: Exception) -> None:
        self._finish_saving()
        self._on_error(exc)

    # ------------------------------------------------------------- photo (kept on this computer)
    def show_photo_menu(self) -> None:
        x = (self.photo.width() - self.photo_menu.sizeHint().width()) // 2
        self.photo_menu.popup(self.photo.mapToGlobal(QPoint(x, self.photo.height() + 6)))

    def choose_photo_file(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a profile photo", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All files (*)",
        )
        return path

    def choose_photo(self) -> None:
        path = self.choose_photo_file()
        if not path:
            return
        self.banner.clear()
        run_task(self, self._facade.set_profile_photo, path, on_success=self._on_photo_saved,
                 on_error=self._on_error)

    def _on_photo_saved(self, result: ValidationDTO) -> None:
        if not result.is_valid:
            self.banner.show_error(" ".join(result.errors.values()))
            return
        self._photo_changed(result.message)

    def delete_photo(self) -> None:
        self.banner.clear()
        run_task(self, self._facade.remove_profile_photo,
                 on_success=lambda _: self._photo_changed("Your photo was removed."), on_error=self._on_error)

    def _photo_changed(self, message: str) -> None:
        user = self._facade.get_current_user() or self._user
        self.set_user(user)
        self.banner.show_success(message)
        self.user_changed.emit(user)

    # ------------------------------------------------------------- refresh
    def reload(self) -> None:
        """Fetch the details again from the server."""
        self.banner.clear()
        run_task(self, self._facade.reload_current_user, on_success=self._on_reloaded, on_error=self._on_error)

    def _on_reloaded(self, user: UserDTO) -> None:
        self.set_user(user)
        self.user_changed.emit(user)

    def _on_error(self, exc: Exception) -> None:
        if isinstance(exc, SessionExpiredError):
            self.session_expired.emit()
        else:
            self.banner.show_error(str(exc) if isinstance(exc, AuthError) else "Something went wrong. Please try again.")


class SignupDetailsDialog(QDialog):
    """What the user gave when signing up, and when that was."""

    def __init__(self, user: UserDTO, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sign-up details")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {theme.WHITE}; }}")

        title = QLabel("Sign-up details")
        title.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 16pt; color: {theme.INK};")
        self.values: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        rows = [
            ("full_name", "Full name", user.full_name or "—"),
            ("username", "Username", user.username),
            ("email", "Email", format_email(user)),
            ("phone", "Phone", user.phone_number or "—"),
            ("provider", "Signed up with", format_provider(user)),
            ("created", "Signed up on", format_date(user.created_at)),
        ]
        for row, (key, name, text) in enumerate(rows):
            value = QLabel(text)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setStyleSheet(f"color: {theme.INK};")
            grid.addWidget(QLabel(name, objectName="Muted"), row, 0)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)

        close = QPushButton("Close", objectName="SecondaryButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addLayout(grid)
        layout.addLayout(buttons)
