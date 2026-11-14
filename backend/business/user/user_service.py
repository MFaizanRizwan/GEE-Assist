"""Class diagram: UserService. Desktop-side authentication logic on top of the auth server."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from backend.auth_exceptions import AuthError, SessionExpiredError
from backend.business.user.i_user_service import IUserService
from backend.data.auth_session import AuthSession
from backend.data.clients.i_auth_api_client import IAuthApiClient
from backend.data.session_store import ISessionStore
from backend.dto.user_dto import (
    GoogleSignInDTO,
    SessionInfoDTO,
    SignupDTO,
    SignupResultDTO,
    UserDTO,
    UserPageDTO,
    VerificationStatusDTO,
)

# Default length of a "Keep me signed in" session (SESSION_DURATION in .env).
DEFAULT_SESSION_DURATION = 7 * 24 * 3600


class UserService(IUserService):
    def __init__(
        self,
        api: IAuthApiClient,
        session_store: ISessionStore,
        clock: Callable[[], float] = time.monotonic,
        session_duration: float = DEFAULT_SESSION_DURATION,
        wall_clock: Callable[[], float] = time.time,
        session: AuthSession | None = None,
    ):
        """``clock`` times access tokens within this run; ``wall_clock`` (seconds since the
        epoch) times the saved session across launches, which lasts ``session_duration`` seconds.
        ``session`` holds the tokens; pass one to share it with the DAOs that call the server."""
        self._api = api
        self._store = session_store
        self._session = session or AuthSession(api, session_store, clock)
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
        data = self._session.authorized(lambda token: self._api.list_users(token, skip, limit))
        return UserPageDTO(
            total=int(data.get("total", 0)),
            items=[UserDTO.from_api(item) for item in data.get("items", [])],
            skip=skip,
            limit=limit,
        )

    def get_user(self, user_id: str) -> UserDTO:
        return UserDTO.from_api(self._session.authorized(lambda token: self._api.get_user(token, user_id)))

    def set_user_role(self, user_id: str, role: str) -> UserDTO:
        if role not in ("admin", "user"):
            raise AuthError(f"Unknown role '{role}'.")
        return UserDTO.from_api(
            self._session.authorized(lambda token: self._api.update_user_role(token, user_id, role))
        )

    def set_user_active(self, user_id: str, is_active: bool) -> UserDTO:
        return UserDTO.from_api(
            self._session.authorized(lambda token: self._api.update_user_status(token, user_id, is_active))
        )

    # ------------------------------------------------------------- helpers
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
