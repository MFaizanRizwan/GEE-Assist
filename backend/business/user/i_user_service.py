from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.user_dto import (
    GoogleSignInDTO,
    NewUserDTO,
    SessionInfoDTO,
    SignupDTO,
    SignupResultDTO,
    UserDTO,
    UserPageDTO,
    VerificationStatusDTO,
)
from backend.dto.validation_dto import ValidationDTO
from backend.dto.version_dto import AppVersionDTO


class IUserService(ABC):
    """Class diagram: IUserService. Sign-up, sign-in, the current session and user administration.

    Methods talk to the network and block, so the UI calls them from a background worker.
    Failures raise ``backend.auth_exceptions.AuthError`` subclasses.
    """

    # ------------------------------------------------------------- server
    @abstractmethod
    def is_server_available(self) -> bool: ...

    @abstractmethod
    def check_app_version(self) -> AppVersionDTO | None: ...

    # ------------------------------------------------------------- session
    @property
    @abstractmethod
    def current_user(self) -> UserDTO | None: ...

    @abstractmethod
    def log_in(self, username: str, password: str, remember: bool = False) -> UserDTO: ...

    @abstractmethod
    def restore_session(self) -> UserDTO | None:
        """Signs in with the refresh token saved by "Keep me signed in". None if there is none / it expired."""

    @abstractmethod
    def reload_current_user(self) -> UserDTO: ...

    @abstractmethod
    def get_session_info(self) -> SessionInfoDTO:
        """The current session: whether it is saved, until when, and when the access token renews."""

    @abstractmethod
    def log_out(self) -> None: ...

    @abstractmethod
    def set_session_duration(self, seconds: float) -> None:
        """How long "Keep me signed in" lasts from the next sign-in on."""

    # ------------------------------------------------------------- sign-up / verification
    @abstractmethod
    def sign_up(self, data: SignupDTO) -> SignupResultDTO: ...

    @abstractmethod
    def get_verification_status(self, verification_token: str) -> VerificationStatusDTO: ...

    @abstractmethod
    def resend_verification_email(self, verification_token: str, new_email: str | None = None) -> str: ...

    # ------------------------------------------------------------- Google
    @abstractmethod
    def start_google_sign_in(self) -> GoogleSignInDTO: ...

    @abstractmethod
    def poll_google_sign_in(self, session_id: str, remember: bool = False) -> UserDTO | None:
        """The signed-in user, or None while the user is still in the browser."""

    # ------------------------------------------------------------- admin
    @abstractmethod
    def list_users(self, skip: int = 0, limit: int = 50) -> UserPageDTO: ...

    @abstractmethod
    def get_user(self, user_id: str) -> UserDTO: ...

    @abstractmethod
    def set_user_role(self, user_id: str, role: str) -> UserDTO: ...

    @abstractmethod
    def set_user_active(self, user_id: str, is_active: bool) -> UserDTO: ...

    @abstractmethod
    def find_user_by_email(self, email: str) -> UserDTO | None: ...

    @abstractmethod
    def create_user(self, user: NewUserDTO) -> ValidationDTO:
        """Admins: add an account. Invalid or already-used fields come back in ``errors``."""

    @abstractmethod
    def delete_user(self, user_id: str) -> bool:
        """Admins: delete someone else's account. False if it no longer existed."""

    # ------------------------------------------------------------- forgot password
    @abstractmethod
    def start_forgot_password(self, identifier: str) -> dict[str, Any]:
        """Request a password reset link sent to email."""

    @abstractmethod
    def poll_forgot_password(self, session_id: str) -> bool:
        """Poll if email link was verified in browser. Returns True when verified."""

    @abstractmethod
    def complete_forgot_password(
        self, session_id: str, new_password: str, confirm_password: str
    ) -> ValidationDTO:
        """Set new password after email verification."""

    # ------------------------------------------------------------- manage account
    @abstractmethod
    def update_user(self, user: UserDTO) -> ValidationDTO:
        """Save changed details: your own name, username and phone; admins also others' email, role
        and status. Invalid or already-used fields come back in ``errors`` (nothing is saved then)."""

    @abstractmethod
    def change_password(
        self, user_id: str, new_password: str, confirm_password: str, current_password: str | None = None
    ) -> ValidationDTO:
        """Your own password needs ``current_password``; admins reset others' without it."""

    @abstractmethod
    def set_profile_photo(self, file_path: str) -> ValidationDTO:
        """Use the image at ``file_path`` as the signed-in user's photo. Kept on this computer only."""

    @abstractmethod
    def get_profile_photo(self, user_id: str | None = None) -> bytes | None:
        """A user's photo saved on this computer (the signed-in user's by default), or None."""

    @abstractmethod
    def remove_profile_photo(self) -> bool:
        """Remove the signed-in user's photo from this computer. False if there was none."""
