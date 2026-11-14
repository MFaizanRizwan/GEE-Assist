"""The signed-in user's tokens for the authentication server.

Shared by the services and DAOs that call the server on the user's behalf: each call goes
through ``authorized``, which supplies a valid access token and renews it when needed.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar

from backend.auth_exceptions import SessionExpiredError
from backend.data.clients.i_auth_api_client import IAuthApiClient
from backend.data.session_store import ISessionStore

T = TypeVar("T")

# Refresh the access token this many seconds before it really expires.
EXPIRY_MARGIN_SECONDS = 30


class AuthSession:
    def __init__(self, api: IAuthApiClient, session_store: ISessionStore, clock: Callable[[], float] = time.monotonic):
        """``clock`` times the access token within this run of the app."""
        self._api = api
        self._store = session_store
        self._clock = clock
        self._lock = threading.RLock()  # workers may call from several threads
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._access_expires_at = 0.0
        self._remember = False

    # ------------------------------------------------------------- state
    @property
    def active(self) -> bool:
        """True from sign-in until sign-out or until the server refuses to renew the tokens."""
        return self._access_token is not None

    @property
    def remembered(self) -> bool:
        return self._remember

    @property
    def has_refresh_token(self) -> bool:
        return bool(self._refresh_token)

    def access_expires_in(self) -> float | None:
        """Seconds until the access token is renewed; None when signed out."""
        with self._lock:
            if not self._access_token:
                return None
            return max(0.0, self._access_expires_at - self._clock())

    # ------------------------------------------------------------- changes
    def start(self, tokens: dict[str, Any], remember: bool) -> None:
        """Keep the tokens of a sign-in or refresh; with ``remember`` the refresh token is saved for next launch."""
        with self._lock:
            self._access_token = tokens["access_token"]
            self._refresh_token = tokens.get("refresh_token") or self._refresh_token
            self._access_expires_at = self._clock() + int(tokens.get("expires_in", 0)) - EXPIRY_MARGIN_SECONDS
            self._remember = remember
            if remember and self._refresh_token:
                self._store.save_refresh_token(self._refresh_token)

    def clear(self) -> None:
        """Forget the tokens, here and in the saved session."""
        with self._lock:
            self._access_token = None
            self._refresh_token = None
            self._access_expires_at = 0.0
            self._remember = False
        self._store.clear()

    # ------------------------------------------------------------- calls
    def authorized(self, call: Callable[[str], T]) -> T:
        """Run a server call with a valid access token, renewing it once if the server rejects it.

        Raises SessionExpiredError (and signs out) when the tokens can no longer be renewed.
        """
        try:
            return call(self._valid_access_token())
        except SessionExpiredError:
            if not self._refresh_token:
                raise
            return call(self._renew_access_token())

    def _valid_access_token(self) -> str:
        with self._lock:
            if self._access_token and self._clock() < self._access_expires_at:
                return self._access_token
        return self._renew_access_token()

    def _renew_access_token(self) -> str:
        with self._lock:
            if not self._refresh_token:
                raise SessionExpiredError("You are not signed in.", 401)
            try:
                tokens = self._api.refresh(self._refresh_token)
            except SessionExpiredError:
                self.clear()
                raise
            self.start(tokens, self._remember)
            return self._access_token
