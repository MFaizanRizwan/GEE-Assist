"""'Forgot password' page: requests reset link, waits for email click, then sets new password."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from backend.auth_exceptions import AuthError
from backend.business.facade import IBusinessFacade
from frontend.views.auth.base_page import AuthPage, centered_row
from frontend.views.account_dialogs import PASSWORD_HINT
from frontend.widgets.form_widgets import Banner, BusyButton, FormField, PasswordField, link_button
from frontend.widgets.icons import envelope_pixmap
from frontend.workers.task_worker import run_task

POLL_INTERVAL_MS = 2500


class ForgotPasswordPage(AuthPage):
    back_to_login = pyqtSignal(str, str)  # success_message, username_to_prefill

    def __init__(self, facade: IBusinessFacade, parent: QWidget | None = None):
        super().__init__(facade, "Reset your password", "Enter your username or email to receive a password reset link.", parent)
        self._session_id = ""
        self._identifier = ""
        self._checking = False

        # -------------------- Step 1: Identifier input
        self.step1_widget = QWidget()
        step1_layout = QVBoxLayout(self.step1_widget)
        step1_layout.setContentsMargins(0, 0, 0, 0)
        step1_layout.setSpacing(10)

        self.identifier_field = FormField("Username or email", "Your username or email address")
        self.send_link_button = BusyButton("Send reset link", "Sending link…")
        self.back_link1 = link_button("Back to sign in")

        step1_layout.addWidget(self.identifier_field)
        step1_layout.addSpacing(4)
        step1_layout.addWidget(self.send_link_button)
        step1_layout.addSpacing(6)
        step1_layout.addLayout(centered_row(self.back_link1))

        # -------------------- Step 2: Waiting for email link
        self.step2_widget = QWidget()
        step2_layout = QVBoxLayout(self.step2_widget)
        step2_layout.setContentsMargins(0, 0, 0, 0)
        step2_layout.setSpacing(12)

        icon = QLabel()
        icon.setPixmap(envelope_pixmap(64))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.step2_info = QLabel(
            "We sent a password reset link to your email.<br>"
            "Open the link in your browser to verify this request.",
            objectName="Muted",
        )
        self.step2_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step2_info.setWordWrap(True)

        self.waiting_bar = QProgressBar(objectName="BusyBar")
        self.waiting_bar.setRange(0, 0)
        self.waiting_bar.setTextVisible(False)

        self.waiting_label = QLabel("Waiting for you to open the link in your browser…", objectName="Muted")
        self.waiting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.resend_button = BusyButton("Resend email", "Sending…", object_name="SecondaryButton")
        self.back_link2 = link_button("Back to sign in")

        step2_layout.addWidget(icon)
        step2_layout.addWidget(self.step2_info)
        step2_layout.addSpacing(6)
        step2_layout.addWidget(self.waiting_bar)
        step2_layout.addWidget(self.waiting_label)
        step2_layout.addSpacing(6)
        step2_layout.addWidget(self.resend_button)
        step2_layout.addLayout(centered_row(self.back_link2))
        self.step2_widget.hide()

        # -------------------- Step 3: Enter new password
        self.step3_widget = QWidget()
        step3_layout = QVBoxLayout(self.step3_widget)
        step3_layout.setContentsMargins(0, 0, 0, 0)
        step3_layout.setSpacing(10)

        self.new_password = PasswordField("New password", "At least 8 characters", PASSWORD_HINT)
        self.confirm_password = PasswordField("Confirm new password", "Type the new password again")
        self.save_password_button = BusyButton("Set new password", "Saving…")
        self.back_link3 = link_button("Back to sign in")

        step3_layout.addWidget(self.new_password)
        step3_layout.addWidget(self.confirm_password)
        step3_layout.addSpacing(4)
        step3_layout.addWidget(self.save_password_button)
        step3_layout.addSpacing(6)
        step3_layout.addLayout(centered_row(self.back_link3))
        self.step3_widget.hide()

        # Assemble into page body
        self.body.addWidget(self.step1_widget)
        self.body.addWidget(self.step2_widget)
        self.body.addWidget(self.step3_widget)

        # Polling timer
        self._poll_timer = QTimer(self, interval=POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_status)

        # Connections
        self.send_link_button.clicked.connect(self._submit_identifier)
        self.identifier_field.input.returnPressed.connect(self._submit_identifier)
        self.resend_button.clicked.connect(self._resend)
        self.save_password_button.clicked.connect(self._submit_new_password)
        self.new_password.input.returnPressed.connect(self.confirm_password.input.setFocus)
        self.confirm_password.input.returnPressed.connect(self._submit_new_password)

        self.back_link1.clicked.connect(self._leave)
        self.back_link2.clicked.connect(self._leave)
        self.back_link3.clicked.connect(self._leave)

    # ------------------------------------------------------------------ API
    def reset(self) -> None:
        super().reset()
        self._poll_timer.stop()
        self._session_id = ""
        self._identifier = ""
        self._checking = False

        self.title.setText("Reset your password")
        self.subtitle.setText("Enter your username or email to receive a password reset link.")

        self.identifier_field.set_text("")
        self.identifier_field.clear_error()
        self.new_password.set_text("")
        self.new_password.clear_error()
        self.confirm_password.set_text("")
        self.confirm_password.clear_error()

        self.send_link_button.set_busy(False)
        self.resend_button.set_busy(False)
        self.save_password_button.set_busy(False)

        self.step1_widget.show()
        self.step2_widget.hide()
        self.step3_widget.hide()

    def focus_first_field(self) -> None:
        if self.step1_widget.isVisible():
            self.identifier_field.input.setFocus()
        elif self.step3_widget.isVisible():
            self.new_password.input.setFocus()

    # ------------------------------------------------------------------ Step 1
    def _submit_identifier(self) -> None:
        self.banner.clear()
        self.identifier_field.clear_error()
        identifier = self.identifier_field.text().strip()
        if not identifier:
            self.identifier_field.set_error("Enter your username or email address")
            return

        self._identifier = identifier
        self.send_link_button.set_busy(True)
        self.identifier_field.input.setEnabled(False)

        run_task(
            self,
            self._facade.start_forgot_password,
            identifier,
            on_success=self._on_link_sent,
            on_error=self._on_start_error,
        )

    def _on_link_sent(self, result: dict) -> None:
        self.send_link_button.set_busy(False)
        self.identifier_field.input.setEnabled(True)
        self._session_id = result.get("session_id", "")
        message = result.get("message", "Password reset link sent to your email.")

        # Switch to step 2: waiting for email link
        self.title.setText("Check your email")
        self.subtitle.setText(message)
        self.banner.clear()

        self.step1_widget.hide()
        self.step2_widget.show()
        self.step3_widget.hide()

        self._poll_timer.start()

    def _on_start_error(self, exc: Exception) -> None:
        self.send_link_button.set_busy(False)
        self.identifier_field.input.setEnabled(True)
        msg = str(exc) if isinstance(exc, AuthError) else "Could not send reset link. Please try again."
        self.banner.show_error(msg)
        self.identifier_field.input.setFocus()

    # ------------------------------------------------------------------ Step 2
    def _poll_status(self) -> None:
        if self._checking or not self._session_id:
            return
        self._checking = True
        run_task(
            self,
            self._facade.poll_forgot_password,
            self._session_id,
            on_success=self._on_poll_success,
            on_error=self._on_poll_error,
        )

    def _on_poll_success(self, verified: bool) -> None:
        self._checking = False
        if verified:
            self._poll_timer.stop()
            self._show_step3()

    def _on_poll_error(self, exc: Exception) -> None:
        self._checking = False
        # If session expired or invalid, stop polling and show error
        if isinstance(exc, AuthError) and exc.status_code == 404:
            self._poll_timer.stop()
            self.banner.show_error(str(exc))

    def _resend(self) -> None:
        if not self._identifier:
            return
        self.banner.clear()
        self.resend_button.set_busy(True)
        run_task(
            self,
            self._facade.start_forgot_password,
            self._identifier,
            on_success=self._on_resend_success,
            on_error=self._on_resend_error,
        )

    def _on_resend_success(self, result: dict) -> None:
        self.resend_button.set_busy(False)
        self._session_id = result.get("session_id", "")
        self.banner.show_info(result.get("message", "A new reset link was sent to your email."))

    def _on_resend_error(self, exc: Exception) -> None:
        self.resend_button.set_busy(False)
        msg = str(exc) if isinstance(exc, AuthError) else "Could not resend email. Try again later."
        self.banner.show_error(msg)

    # ------------------------------------------------------------------ Step 3
    def _show_step3(self) -> None:
        self.title.setText("Choose a new password")
        self.subtitle.setText("Your email is verified! Enter a new password for your account.")
        self.banner.clear()

        self.step1_widget.hide()
        self.step2_widget.hide()
        self.step3_widget.show()

        self.new_password.input.setFocus()

    def _submit_new_password(self) -> None:
        self.banner.clear()
        self.new_password.clear_error()
        self.confirm_password.clear_error()

        new_pass = self.new_password.text()
        confirm_pass = self.confirm_password.text()

        if not new_pass:
            self.new_password.set_error("Enter a new password")
            return
        if len(new_pass) < 8:
            self.new_password.set_error("Must be at least 8 characters")
            return
        if new_pass != confirm_pass:
            self.confirm_password.set_error("Passwords do not match")
            return

        self.save_password_button.set_busy(True)
        self.new_password.input.setEnabled(False)
        self.confirm_password.input.setEnabled(False)

        run_task(
            self,
            self._facade.complete_forgot_password,
            self._session_id,
            new_pass,
            confirm_pass,
            on_success=self._on_password_saved,
            on_error=self._on_save_error,
        )

    def _on_password_saved(self, result) -> None:
        self.save_password_button.set_busy(False)
        self.new_password.input.setEnabled(True)
        self.confirm_password.input.setEnabled(True)

        if not result.is_valid:
            if "new_password" in result.errors:
                self.new_password.set_error(result.errors["new_password"])
            if "confirm_password" in result.errors:
                self.confirm_password.set_error(result.errors["confirm_password"])
            if "form" in result.errors:
                self.banner.show_error(result.errors["form"])
            return

        msg = result.message or "Your password has been reset. You can now sign in with your new password."
        self.back_to_login.emit(msg, self._identifier)

    def _on_save_error(self, exc: Exception) -> None:
        self.save_password_button.set_busy(False)
        self.new_password.input.setEnabled(True)
        self.confirm_password.input.setEnabled(True)
        self.banner.show_error(str(exc) if isinstance(exc, AuthError) else "Could not reset password. Please try again.")

    def _leave(self) -> None:
        self._poll_timer.stop()
        self.back_to_login.emit("", self._identifier)
