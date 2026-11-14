"""Class diagram: UserDAO. Accounts live on the GEE-Assist server; profile photos stay on this computer."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

from backend.auth_exceptions import NotFoundError
from backend.data.auth_session import AuthSession
from backend.data.clients.i_auth_api_client import IAuthApiClient
from backend.data.dao.i_user_dao import IUserDAO
from backend.dto.user_dto import NewUserDTO, UserDTO, UserPageDTO

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")
_PHOTO_SUFFIX = ".img"  # any image format; it is told from the bytes when shown


class UserDAO(IUserDAO):
    def __init__(self, api: IAuthApiClient, session: AuthSession, photo_dir: Path | str):
        """``session`` supplies the signed-in user's access token for the server calls."""
        self._api = api
        self._session = session
        self._photo_dir = Path(photo_dir)

    # ------------------------------------------------------------- accounts (server)
    def save(self, entity: UserDTO) -> UserDTO:
        fields = entity.to_api()
        return UserDTO.from_api(self._session.authorized(lambda token: self._api.update_user(token, entity.id, fields)))

    def find_by_id(self, id: str) -> UserDTO | None:  # noqa: A002
        try:
            return UserDTO.from_api(self._session.authorized(lambda token: self._api.get_user(token, id)))
        except NotFoundError:
            return None

    def find_by_email(self, email: str) -> UserDTO | None:
        try:
            return UserDTO.from_api(self._session.authorized(lambda token: self._api.find_user_by_email(token, email)))
        except NotFoundError:
            return None

    def find_all(self, skip: int = 0, limit: int = 50) -> UserPageDTO:
        data = self._session.authorized(lambda token: self._api.list_users(token, skip, limit))
        return UserPageDTO(
            total=int(data.get("total", 0)),
            items=[UserDTO.from_api(item) for item in data.get("items", [])],
            skip=skip,
            limit=limit,
        )

    def delete(self, id: str) -> bool:  # noqa: A002
        try:
            self._session.authorized(lambda token: self._api.delete_user(token, id))
        except NotFoundError:
            return False
        self.delete_photo(id)
        return True

    def create(self, entity: NewUserDTO) -> UserDTO:
        payload = entity.to_api()
        return UserDTO.from_api(self._session.authorized(lambda token: self._api.create_user(token, payload)))

    def change_password(self, id: str, new_password: str, current_password: str | None = None) -> bool:  # noqa: A002
        self._session.authorized(lambda token: self._api.change_password(token, id, new_password, current_password))
        return True

    # ------------------------------------------------------------- profile photos (this computer)
    def save_photo(self, id: str, image: bytes) -> bool:  # noqa: A002
        path = self._photo_path(id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the old photo and swapped in, so a failed write never loses it.
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(image)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return True

    def find_photo(self, id: str) -> bytes | None:  # noqa: A002
        path = self._photo_path(id)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning("Could not read the profile photo %s", path, exc_info=True)
            return None

    def delete_photo(self, id: str) -> bool:  # noqa: A002
        path = self._photo_path(id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _photo_path(self, user_id: str) -> Path:
        safe = _SAFE_ID.sub("_", user_id)
        if not safe.strip("_"):
            raise ValueError("A user id is needed to keep a profile photo.")
        return self._photo_dir / f"{safe}{_PHOTO_SUFFIX}"
