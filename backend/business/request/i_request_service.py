from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto import FormDTO, PlaceDTO, ValidationDTO
from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO


class IRequestService(ABC):
    """Class diagram: IRequestService (submitQuery, validateForm, importAOI, saveProject, listProjects).

    It also keeps the open project: downloads and analysis results go into its folder.
    Project problems raise ``backend.exceptions.ProjectError``.
    """

    @abstractmethod
    def submit_query(self, text: str) -> FormDTO:
        """UC-02: accept a natural-language query and keep it."""

    @abstractmethod
    def validate_form(self, form: FormDTO) -> ValidationDTO:
        """UC-03: validate the form parameters; valid forms are kept."""

    @abstractmethod
    def check_form(self, form: FormDTO) -> ValidationDTO:
        """UC-03 checks only: like ``validate_form``, but the form is not kept."""

    @abstractmethod
    def import_aoi(self, file_path: str) -> str:
        """UC-04: read a GeoJSON file and return its geometry as a JSON string."""

    @abstractmethod
    def search_place(self, name: str) -> list[PlaceDTO]:
        """Find a city, region or country by name; each match carries its exact boundary as the AOI."""

    @abstractmethod
    def get_kept_requests(self) -> list[FormDTO]:
        """Requests kept so far this session."""

    # ------------------------------------------------------------- projects
    @abstractmethod
    def save_project(self, project: ProjectDTO) -> bool:
        """Write the project's folder and remember where it is."""

    @abstractmethod
    def list_projects(self, user_id: str) -> list[ProjectDTO]:
        """The user's projects whose folders still exist, most recently opened first."""

    @abstractmethod
    def create_project(self, name: str, location: str, owner_id: str = "") -> ProjectDTO:
        """Make ``<location>/<name>`` with its downloads and analysis folders, and open it."""

    @abstractmethod
    def open_project(self, folder: str, owner_id: str = "") -> ProjectDTO:
        """Open the project in ``folder`` (a folder made by create_project)."""

    @abstractmethod
    def rename_project(self, new_name: str) -> ProjectDTO:
        """Rename the open project; its folder is renamed too."""

    @abstractmethod
    def move_project(self, new_location: str) -> ProjectDTO:
        """Move the open project's folder into ``new_location``."""

    @abstractmethod
    def close_project(self) -> None: ...

    @abstractmethod
    def get_current_project(self) -> ProjectDTO | None: ...

    @abstractmethod
    def record_analysis_result(self, result) -> AnalysisRecordDTO:
        """Keep an analysis result (a ResultDTO) in the open project's analysis_results.json."""

    @abstractmethod
    def get_analysis_results(self, project: ProjectDTO) -> list[AnalysisRecordDTO]:
        """The project's analysis results, newest first."""
