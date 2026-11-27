"""Dialogs for managing accounts: edit details, change or reset a password, create a user.

Each runs its request in the background. Problems with particular fields (from the app's own
checks or from the server) are shown under those fields; anything else in the banner.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from backend.auth_exceptions import AuthError, SessionExpiredError
from backend.business.facade import IBusinessFacade
from backend.dto.user_dto import NewUserDTO, UserDTO
from backend.dto.validation_dto import ValidationDTO
from frontend import theme
from frontend.widgets.form_widgets import Banner, BusyButton, FormField, PasswordField
from frontend.workers.task_worker import run_task

PHONE_HINT = "International format with country code, e.g. +923001234567"
USERNAME_HINT = "3-30 characters: letters, digits, '_' or '.'"
PASSWORD_HINT = "At least 8 characters"
ROLES = (("User", "user"), ("Administrator", "admin"))


class AccountDialog(QDialog):
    """A titled form with a banner and Cancel / save buttons; ``_submit`` sends it."""

    session_expired = pyqtSignal()

    def __init__(self, facade: IBusinessFacade, title: str, subtitle: str, save_text: str, busy_text: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._facade = facade
        self.result_message = ""  # the success message, for the window that opened the dialog
        self.fields: dict[str, FormField] = {}
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.WHITE}; }}"
            f"QComboBox {{ background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG};"
            f" border-radius: 8px; padding: 8px 10px; }}"
        )

        heading = QLabel(title)
        heading.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 16.2pt; color: {theme.INK};")
        self.subtitle = QLabel(subtitle, objectName="Muted")
        self.subtitle.setWordWrap(True)
        self.banner = Banner()

        self.cancel_button = QPushButton("Cancel", objectName="SecondaryButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = BusyButton(save_text, busy_text)
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._submit)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        self.form = QVBoxLayout()
        self.form.setSpacing(12)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)
        layout.addWidget(heading)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.banner)
        layout.addLayout(self.form)
        layout.addSpacing(4)
        layout.addLayout(buttons)

    def add_field(self, key: str, field: FormField, value: str = "") -> FormField:
        field.set_text(value)
        field.input.returnPressed.connect(self._submit)
        self.fields[key] = field
        self.form.addWidget(field)
        return field

    def show_errors(self, errors: dict[str, str]) -> None:
        """Each message under its field; the rest (e.g. ``form``) in the banner."""
        elsewhere = []
        for key, message in errors.items():
            if key in self.fields:
                self.fields[key].set_error(message)
            else:
                elsewhere.append(message)
        if elsewhere:
            self.banner.show_error("\n".join(elsewhere))
        first = next((self.fields[key] for key in errors if key in self.fields), None)
        if first is not None:
            first.input.setFocus()

    # ------------------------------------------------------------- sending
    def _submit(self) -> None:
        raise NotImplementedError

    def _send(self, call: Callable[..., ValidationDTO], *args: Any) -> None:
        if not self.save_button.isEnabled():
            return  # already sending
        self.banner.clear()
        for field in self.fields.values():
            field.clear_error()
        self.save_button.set_busy(True)
        run_task(self, call, *args, on_success=self._on_result, on_error=self._on_error)

    def _on_result(self, result: ValidationDTO) -> None:
        self.save_button.set_busy(False)
        if not result.is_valid:
            self.show_errors(result.errors)
            return
        self.result_message = result.message
        self.accept()

    def _on_error(self, exc: Exception) -> None:
        self.save_button.set_busy(False)
        if isinstance(exc, SessionExpiredError):
            self.session_expired.emit()
            self.reject()
            return
        self.banner.show_error(str(exc) if isinstance(exc, AuthError) else "Something went wrong. Please try again.")


class EditDetailsDialog(AccountDialog):
    """Name, username and phone; an admin editing someone else can also change the email address."""

    def __init__(self, facade: IBusinessFacade, user: UserDTO, allow_email: bool = False,
                 parent: QWidget | None = None):
        own = not allow_email
        super().__init__(
            facade, "Edit your details" if own else f"Edit {user.full_name}",
            "Changes are saved to your GEE-Assist account." if own
            else "A new email address must be verified again: a link is sent to it.",
            "Save changes", "Saving…", parent,
        )
        self._user = user
        self.add_field("full_name", FormField("Full name", "Your full name"), user.full_name)
        username_field = self.add_field("username", FormField("Username", "username", "Username cannot be changed once set"), user.username)
        username_field.input.setEnabled(False)
        username_field.setToolTip("Username cannot be changed once set.")
        if allow_email:
            self.add_field("email", FormField("Email", "name@example.com"), user.email or "")
        self.add_field("phone_number", FormField("Phone number", "+923001234567", PHONE_HINT),
                       user.phone_number or "")
        if own:
            email = QLabel(f"Email: {user.email or '—'}\nOnly an administrator can change your email address.",
                           objectName="FieldHint")
            email.setWordWrap(True)
            self.form.addWidget(email)
        self.fields["full_name"].input.setFocus()

    def edited_user(self) -> UserDTO:
        changes = {key: field.text() for key, field in self.fields.items()}
        return dataclasses.replace(self._user, **changes)

    def _submit(self) -> None:
        self._send(self._facade.update_user, self.edited_user())


class ChangePasswordDialog(AccountDialog):
    """Your own password (needs the current one), or an admin resetting someone else's."""

    def __init__(self, facade: IBusinessFacade, user: UserDTO, own: bool = True, parent: QWidget | None = None):
        super().__init__(
            facade, "Change password" if own else f"Reset password for {user.full_name}",
            "Use at least 8 characters. Other signed-in devices stay signed in." if own
            else "They sign in with this password from now on. Tell them it has changed.",
            "Change password" if own else "Reset password", "Saving…", parent,
        )
        self._user_id = user.id
        self._own = own
        if own:
            self.add_field("current_password", PasswordField("Current password", "Your current password"))
        self.add_field("new_password", PasswordField("New password", "New password", PASSWORD_HINT))
        self.add_field("confirm_password", PasswordField("Confirm new password", "Type it again"))
        next(iter(self.fields.values())).input.setFocus()

    def _submit(self) -> None:
        current = self.fields["current_password"].text() if self._own else None
        self._send(self._facade.change_password, self._user_id, self.fields["new_password"].text(),
                   self.fields["confirm_password"].text(), current)


class CreateUserDialog(AccountDialog):
    """An admin adds an account. The person verifies the email address when they first sign in."""

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(facade, "Add a user",
                         "A verification link is sent to the email address; they confirm it at their first sign-in.",
                         "Create account", "Creating…", parent)
        self.add_field("full_name", FormField("Full name", "Their full name"))
        self.add_field("email", FormField("Email", "name@example.com"))
        self.add_field("phone_number", FormField("Phone number", "+923001234567", PHONE_HINT))
        self.add_field("username", FormField("Username", "username", USERNAME_HINT))
        self.add_field("password", PasswordField("Password", "Password", PASSWORD_HINT))
        self.add_field("confirm_password", PasswordField("Confirm password", "Type it again"))
        self.role = QComboBox()
        for label, value in ROLES:
            self.role.addItem(label, value)
        self.form.addWidget(QLabel("Role", objectName="FieldLabel"))
        self.form.addWidget(self.role)
        self.fields["full_name"].input.setFocus()

    def new_user(self) -> NewUserDTO:
        text = {key: field.text() for key, field in self.fields.items()}
        return NewUserDTO(full_name=text["full_name"], email=text["email"], phone_number=text["phone_number"],
                          username=text["username"], password=text["password"], role=self.role.currentData())

    def _submit(self) -> None:
        if self.fields["password"].text() != self.fields["confirm_password"].text():
            self.fields["confirm_password"].set_error("Passwords do not match")
            return
        self._send(self._facade.create_user, self.new_user())
