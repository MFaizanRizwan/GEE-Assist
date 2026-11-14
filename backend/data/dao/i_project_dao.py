from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO


class IProjectDAO(ABC):
    """Class diagram: IProjectDAO (save, findById, findByUserId, findAll, delete).

    Projects are folders on this computer. A JSON history file remembers where they are,
    so the recent ones can be listed and reopened.
    """

    @abstractmethod
    def save(self, entity: ProjectDTO) -> bool:
        """Write the project's folder (``project.json``, ``downloads/``, ``analysis/``) and remember it."""

    @abstractmethod
    def find_by_id(self, id: str) -> ProjectDTO | None:  # noqa: A002 (name from the class diagram)
        ...

    @abstractmethod
    def find_by_user_id(self, user_id: str) -> list[ProjectDTO]:
        """The user's projects, most recently opened first."""

    @abstractmethod
    def find_all(self) -> list[ProjectDTO]:
        """Every remembered project, most recently opened first."""

    @abstractmethod
    def delete(self, id: str) -> bool:  # noqa: A002
        """Forget the project. Its folder and files are never deleted."""

    # ------------------------------------------------------------- beyond the diagram's CRUD
    @abstractmethod
    def load_folder(self, folder: str) -> ProjectDTO | None:
        """The project in ``folder`` (from its ``project.json``), or None if it is not a project."""

    @abstractmethod
    def move(self, entity: ProjectDTO, new_folder: str) -> ProjectDTO:
        """Rename or move the project folder to ``new_folder`` and remember the new place."""

    @abstractmethod
    def save_analysis_result(self, project: ProjectDTO, record: AnalysisRecordDTO) -> bool:
        """Add the record to the project's ``analysis_results.json``, or replace the one with its id."""

    @abstractmethod
    def find_analysis_results(self, project: ProjectDTO) -> list[AnalysisRecordDTO]:
        """The project's analysis results, newest first."""
