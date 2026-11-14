"""Class diagram: UserService. Desktop-side authentication logic on top of the auth server."""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.auth_exceptions import (
    AuthError,
    ConflictError,
    FieldValidationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    SessionExpiredError,
)
from backend.business.user.i_user_service import IUserService
from backend.business.user.signup_validation import (
    email_error,
    full_name_error,
    normalize_full_name,
    normalize_phone_number,
    password_error,
    phone_number_error,
    username_error,
)
from backend.data.auth_session import AuthSession
from backend.data.clients.i_auth_api_client import IAuthApiClient
from backend.data.i_data_facade import IDataFacade
from backend.data.session_store import ISessionStore
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

# Default length of a "Keep me signed in" session (SESSION_DURATION in .env).
DEFAULT_SESSION_DURATION = 7 * 24 * 3600

ROLES = ("user", "admin")
MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_FORMATS = "PNG, JPEG, GIF, BMP or WebP"


def image_format(data: bytes) -> str | None:
    """The image format told from the file's first bytes, or None if it is not a supported image."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if data.startswith(b"BM"):
        return "BMP"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WebP"
    return None


class UserService(IUserService):
    def __init__(
        self,
        api: IAuthApiClient,
        session_store: ISessionStore,
        clock: Callable[[], float] = time.monotonic,
        session_duration: float = DEFAULT_SESSION_DURATION,
        wall_clock: Callable[[], float] = time.time,
        session: AuthSession | None = None,
        data_facade: IDataFacade | None = None,
    ):
        """``clock`` times access tokens within this run; ``wall_clock`` (seconds since the
        epoch) times the saved session across launches, which lasts ``session_duration`` seconds.
        ``session`` holds the tokens; pass the one the DataFacade's UserDAO uses.
        ``data_facade`` (class diagram: -dataFacade) stores accounts and profile photos."""
        self._api = api
        self._store = session_store
        self._session = session or AuthSession(api, session_store, clock)
        self._data_facade = data_facade
        self._session_duration = session_duration
        self._wall_clock = wall_clock
        self._user: UserDTO | None = None

    # ------------------------------------------------------------- server
    def is_server_available(self) -> bool:
        return self._api.health()

    # ------------------------------------------------------------- session
    @property
    def current_user(self) -> UserDTO | None:
        # None once the session has ended, also when the server refused to renew it.
        return self._user if self._session.active else None

    def log_in(self, username: str, password: str, remember: bool = False) -> UserDTO:
        username = username.strip().lower()
        if not username or not password:
            raise AuthError("Enter your username and password.")
        return self._start_session(self._api.login(username, password), remember)

    def restore_session(self) -> UserDTO | None:
        refresh_token = self._store.load_refresh_token()
        if not refresh_token:
            return None
        expires_at = self._store.load_expiry()
        if expires_at is None or self._wall_clock() >= expires_at:
            self._store.clear()  # "Keep me signed in" has run out: sign in again
            return None
        try:
            tokens = self._api.refresh(refresh_token)
            user = UserDTO.from_api(self._api.me(tokens["access_token"]))
        except SessionExpiredError:
            self._store.clear()
            return None
        except AuthError as exc:
            # Disabled or no longer verified: forget the saved session. Network errors keep it.
            if exc.status_code in (401, 403):
                self._store.clear()
                return None
            raise
        self._session.start(tokens, remember=True)
        self._user = user
        return user

    def reload_current_user(self) -> UserDTO:
        user = UserDTO.from_api(self._session.authorized(self._api.me))
        self._user = user
        return user

    def get_session_info(self) -> SessionInfoDTO:
        signed_in = self.current_user is not None
        remembered = self._session.remembered
        saved_until = None
        if signed_in and remembered:
            expires_at = self._store.load_expiry()
            if expires_at is not None:
                saved_until = datetime.fromtimestamp(expires_at).astimezone()
        return SessionInfoDTO(
            signed_in=signed_in,
            remembered=remembered,
            saved_until=saved_until,
            access_expires_in=self._session.access_expires_in(),
            has_refresh_token=self._session.has_refresh_token,
        )

    def log_out(self) -> None:
        self._user = None
        self._session.clear()

    # ------------------------------------------------------------- sign-up / verification
    def sign_up(self, data: SignupDTO) -> SignupResultDTO:
        return SignupResultDTO.from_api(self._api.signup(data.to_api()))

    def get_verification_status(self, verification_token: str) -> VerificationStatusDTO:
        return VerificationStatusDTO.from_api(self._api.verification_status(verification_token))

    def resend_verification_email(self, verification_token: str, new_email: str | None = None) -> str:
        new_email = (new_email or "").strip().lower() or None
        return self._api.resend_verification_email(verification_token, new_email).get("message", "Email sent.")

    # ------------------------------------------------------------- Google
    def start_google_sign_in(self) -> GoogleSignInDTO:
        return GoogleSignInDTO.from_api(self._api.google_start())

    def poll_google_sign_in(self, session_id: str, remember: bool = False) -> UserDTO | None:
        result = self._api.google_poll(session_id)
        if result is None:
            return None
        return self._start_session(result, remember)

    # ------------------------------------------------------------- admin
    def list_users(self, skip: int = 0, limit: int = 50) -> UserPageDTO:
        return self._data().find_users(skip, limit)

    def get_user(self, user_id: str) -> UserDTO:
        user = self._data().find_user_by_id(user_id)
        if user is None:
            raise NotFoundError("This user no longer exists.", 404)
        return user

    def set_user_role(self, user_id: str, role: str) -> UserDTO:
        if role not in ROLES:
            raise AuthError(f"Unknown role '{role}'.")
        return self._data().save_user(dataclasses.replace(self.get_user(user_id), role=role))

    def set_user_active(self, user_id: str, is_active: bool) -> UserDTO:
        return self._data().save_user(dataclasses.replace(self.get_user(user_id), is_active=is_active))

    def find_user_by_email(self, email: str) -> UserDTO | None:
        email = email.strip().lower()
        return self._data().find_user_by_email(email) if email else None

    def create_user(self, user: NewUserDTO) -> ValidationDTO:
        self._require_admin()
        result = ValidationDTO()
        checks = {
            "full_name": full_name_error(user.full_name),
            "email": email_error(user.email),
            "phone_number": phone_number_error(user.phone_number),
            "username": username_error(user.username),
            "password": password_error(user.password),
            "role": None if user.role in ROLES else "Choose User or Administrator",
        }
        for field, message in checks.items():
            if message:
                result.add_error(field, message)
        if not result.is_valid:
            return result
        cleaned = NewUserDTO(
            full_name=normalize_full_name(user.full_name),
            email=user.email.strip().lower(),
            phone_number=normalize_phone_number(user.phone_number),
            username=user.username.strip().lower(),
            password=user.password,  # never altered
            role=user.role,
        )
        if not self._save_or_collect_errors(result, lambda: self._data().create_user(cleaned)):
            return result
        result.message = (f"Account created for {cleaned.username}. A verification link was sent to "
                          f"{cleaned.email}; they confirm it when they first sign in.")
        return result

    def delete_user(self, user_id: str) -> bool:
        current = self._require_admin()
        if user_id == current.id:
            raise InvalidRequestError("You cannot delete your own account.", 400)
        return self._data().delete_user(user_id)

    # ------------------------------------------------------------- manage account
    def update_user(self, user: UserDTO) -> ValidationDTO:
        current = self._require_user()
        is_self = user.id == current.id
        if not is_self and not current.is_admin:
            raise PermissionDeniedError("You can only change your own account.", 403)
        before = current if is_self else self.get_user(user.id)
        result = ValidationDTO()

        for field, message in (("full_name", full_name_error(user.full_name)),
                               ("username", username_error(user.username))):
            if message:
                result.add_error(field, message)
        phone = normalize_phone_number(user.phone_number or "")
        if phone and (message := phone_number_error(phone)):
            result.add_error("phone_number", message)
        elif not phone and before.phone_number:
            result.add_error("phone_number", "Enter a phone number")  # the server keeps one once set
        email = (user.email or "").strip().lower() or None
        if email != before.email:
            if is_self:
                result.add_error("email", "Ask an administrator to change your email address")
            elif before.auth_provider == "google":
                result.add_error("email", "This account signs in with Google, so its email comes from Google")
            elif message := email_error(email or ""):
                result.add_error("email", message)
        if is_self and user.role != before.role:
            result.add_error("role", "You cannot change your own role")
        if is_self and user.is_active != before.is_active:
            result.add_error("is_active", "You cannot disable your own account")
        if user.role not in ROLES:
            result.add_error("role", "Choose User or Administrator")
        if not result.is_valid:
            return result

        cleaned = dataclasses.replace(
            user,
            full_name=normalize_full_name(user.full_name),
            username=user.username.strip().lower(),
            phone_number=phone or None,
            email=email,
        )
        saved = self._save_or_collect_errors(result, lambda: self._data().save_user(cleaned))
        if saved is None:
            return result
        if is_self:
            self._user = saved
            result.message = "Your details were saved."
        else:
            result.message = f"{saved.full_name}'s details were saved."
            if saved.email != before.email:
                result.message += f" A verification link was sent to {saved.email}."
        return result

    def change_password(
        self, user_id: str, new_password: str, confirm_password: str, current_password: str | None = None
    ) -> ValidationDTO:
        current = self._require_user()
        is_self = user_id == current.id
        if not is_self and not current.is_admin:
            raise PermissionDeniedError("You can only change your own password.", 403)
        result = ValidationDTO()
        if is_self and current.auth_provider == "google":
            result.add_error("form", "You sign in with Google, so there is no password to change.")
            return result
        if is_self and not current_password:
            result.add_error("current_password", "Enter your current password")
        if message := password_error(new_password):
            result.add_error("new_password", message)
        elif confirm_password != new_password:
            result.add_error("confirm_password", "Passwords do not match")
        if not result.is_valid:
            return result

        changed = self._save_or_collect_errors(
            result, lambda: self._data().change_password(user_id, new_password, current_password if is_self else None)
        )
        if changed:
            result.message = "Your password was changed." if is_self else "The password was reset."
        return result

    def set_profile_photo(self, file_path: str) -> ValidationDTO:
        current = self._require_user()
        result = ValidationDTO()
        path = Path(file_path)
        try:
            size = path.stat().st_size
            if size > MAX_PHOTO_BYTES:
                result.add_error("photo", f"Choose an image smaller than {MAX_PHOTO_BYTES // (1024 * 1024)} MB.")
                return result
            image = path.read_bytes()
        except OSError:
            result.add_error("photo", "The image could not be read. Choose another file.")
            return result
        if image_format(image) is None:
            result.add_error("photo", f"This file is not a supported image. Use {PHOTO_FORMATS}.")
            return result
        self._data().save_profile_photo(current.id, image)
        result.message = "Your photo was updated. It is kept on this computer only."
        return result

    def get_profile_photo(self, user_id: str | None = None) -> bytes | None:
        if user_id is None:
            current = self.current_user
            if current is None:
                return None
            user_id = current.id
        return self._data().find_profile_photo(user_id)

    def remove_profile_photo(self) -> bool:
        return self._data().delete_profile_photo(self._require_user().id)

    # ------------------------------------------------------------- helpers
    def _data(self) -> IDataFacade:
        if self._data_facade is None:
            raise AuthError("User accounts are not set up in this build.")
        return self._data_facade

    def _require_user(self) -> UserDTO:
        user = self.current_user
        if user is None:
            raise SessionExpiredError("You are not signed in.", 401)
        return user

    def _require_admin(self) -> UserDTO:
        user = self._require_user()
        if not user.is_admin:
            raise PermissionDeniedError("Only administrators can manage other accounts.", 403)
        return user

    @staticmethod
    def _save_or_collect_errors(result: ValidationDTO, save: Callable[[], Any]) -> Any:
        """Run ``save``; the server's complaints about particular fields go into ``result``."""
        try:
            return save()
        except ConflictError as exc:
            result.add_error(exc.field or "form", exc.message)
        except FieldValidationError as exc:
            for field, message in (exc.field_errors or {"form": exc.message}).items():
                result.add_error(field, message)
        except InvalidRequestError as exc:  # e.g. a rule only the server knows about
            result.add_error("form", exc.message)
        return None
    def _start_session(self, login_response: dict[str, Any], remember: bool) -> UserDTO:
        user = UserDTO.from_api(login_response["user"])
        self._session.start(login_response, remember)
        self._user = user
        if remember:
            # Counted from this sign-in; refreshing tokens later does not extend it.
            self._store.save_expiry(self._wall_clock() + self._session_duration)
        else:
            self._store.clear()  # don't keep a session saved by an earlier "Keep me signed in"
        return user
