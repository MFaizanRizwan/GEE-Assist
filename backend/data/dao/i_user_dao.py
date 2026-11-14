from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.user_dto import NewUserDTO, UserDTO, UserPageDTO


class IUserDAO(ABC):
    """Class diagram: IUserDAO (save, findById, findByEmail, findAll, delete).

    Accounts are kept by the GEE-Assist server; profile photos only on this computer.
    Server failures raise ``backend.auth_exceptions.AuthError`` subclasses.
    """

    @abstractmethod
    def save(self, entity: UserDTO) -> UserDTO:
        """Store the user's details. Returns the user as stored (the server tidies the values),
        rather than the diagram's boolean, so the caller sees what was saved."""

    @abstractmethod
    def find_by_id(self, id: str) -> UserDTO | None:  # noqa: A002 (name from the class diagram)
        """The user with this id, or None. Administrators only."""

    @abstractmethod
    def find_by_email(self, email: str) -> UserDTO | None:
        """The user with this email address, or None. Administrators only."""

    @abstractmethod
    def find_all(self, skip: int = 0, limit: int = 50) -> UserPageDTO:
        """One page of every user, newest first. Administrators only."""

    @abstractmethod
    def delete(self, id: str) -> bool:  # noqa: A002
        """Delete the user and their local photo. False if there was no such user. Administrators only."""

    # ------------------------------------------------------------- beyond the diagram's CRUD
    @abstractmethod
    def create(self, entity: NewUserDTO) -> UserDTO:
        """Add an account (it needs a password, which UserDTO does not carry). Administrators only."""

    @abstractmethod
    def change_password(self, id: str, new_password: str, current_password: str | None = None) -> bool:  # noqa: A002
        """``current_password`` is required for your own account; administrators reset others' without it."""

    @abstractmethod
    def save_photo(self, id: str, image: bytes) -> bool:  # noqa: A002
        """Keep ``image`` as the user's profile photo on this computer, replacing any earlier one."""

    @abstractmethod
    def find_photo(self, id: str) -> bytes | None:  # noqa: A002
        """The user's profile photo on this computer, or None."""

    @abstractmethod
    def delete_photo(self, id: str) -> bool:  # noqa: A002
        """Remove the user's profile photo from this computer. False if there was none."""
