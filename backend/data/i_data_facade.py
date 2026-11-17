from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from backend.data.clients.i_gee_client import ProgressCallback, StopCheck
from backend.dto import CheckDTO, ChunkDTO, FormDTO, PlaceDTO
from backend.dto.analysis_dto import FormulaDTO
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO
from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO
from backend.dto.user_dto import NewUserDTO, UserDTO, UserPageDTO


class IDataFacade(ABC):
    """Class diagram: IDataFacade. The business services' only way to reach
    external systems (Gemini, GEE) and storage (DAOs).

    The LLM and GEE operations exist so far; the DAO operations are added with
    their use cases.
    """

    @abstractmethod
    def process_query(self, prompt: str) -> FormDTO:
        """Interpret a natural-language request (delegates to IGeminiClient)."""

    @abstractmethod
    def generate_explanation(self, request: ExplanationRequestDTO) -> ExplanationDTO:
        """UC-08: Gemini's explanation of an analysis result (delegates to IGeminiClient)."""

    @abstractmethod
    def search_places(self, query: str) -> list[PlaceDTO]:
        """Places (city, region, country) matching ``query``, with their boundaries
        (delegates to IGeocodingClient).

        Raises:
            PlaceSearchError: place search is unavailable or failed.
        """

    @abstractmethod
    def fetch_chunk(
        self,
        chunk: ChunkDTO,
        path: str,
        on_progress: Optional[ProgressCallback] = None,
        should_stop: Optional[StopCheck] = None,
    ) -> bool:
        """UC-05: download one chunk from GEE to ``path`` (delegates to IGEEClient)."""

    @abstractmethod
    def configure_gee_project(self, project: str) -> None:
        """Use this Google Cloud project for Earth Engine from now on (delegates to IGEEClient)."""

    @abstractmethod
    def configure_gemini_key(self, api_key: str) -> None:
        """Use this Gemini API key from now on (delegates to IGeminiClient)."""

    @abstractmethod
    def validate_access(self) -> bool:
        """True if Google Earth Engine can be used (delegates to IGEEClient)."""

    @abstractmethod
    def diagnose_gee(self) -> list[CheckDTO]:
        """The Earth Engine set-up checked step by step (delegates to IGEEClient)."""

    @abstractmethod
    def begin_gee_sign_in(self) -> str:
        """Start the Earth Engine browser sign-in; returns the page to open (delegates to IGEEClient)."""

    @abstractmethod
    def complete_gee_sign_in(self, should_stop: Optional[StopCheck] = None) -> str:
        """Wait for the browser and save the sign-in; returns the credentials file (delegates to IGEEClient)."""

    @abstractmethod
    def cancel_gee_sign_in(self) -> None:
        """Stop waiting for the Earth Engine browser sign-in (delegates to IGEEClient)."""

    @abstractmethod
    def list_formulas(self) -> list[FormulaDTO]:
        """Every spectral index and method, in category order (delegates to IFormulaDAO)."""

    @abstractmethod
    def get_formula(self, key: str) -> FormulaDTO | None:
        """The formula with this key or alias, or None (delegates to IFormulaDAO)."""

    @abstractmethod
    def formula_categories(self) -> list[tuple[str, str]]:
        """(sub-type, what it is for), in display order (delegates to IFormulaDAO)."""

    @abstractmethod
    def analysis_groups(self) -> list[tuple[str, str, str, tuple[str, ...]]]:
        """(analysis, label, what it is for, its sub-types) of the four analyses (delegates to IFormulaDAO)."""

    # ------------------------------------------------------------- user accounts (delegate to IUserDAO)
    @abstractmethod
    def save_user(self, user: UserDTO) -> UserDTO:
        """Store the user's details; returns them as stored."""

    @abstractmethod
    def find_user_by_id(self, user_id: str) -> UserDTO | None: ...

    @abstractmethod
    def find_user_by_email(self, email: str) -> UserDTO | None: ...

    @abstractmethod
    def find_users(self, skip: int = 0, limit: int = 50) -> UserPageDTO: ...

    @abstractmethod
    def delete_user(self, user_id: str) -> bool: ...

    @abstractmethod
    def create_user(self, user: NewUserDTO) -> UserDTO: ...

    @abstractmethod
    def change_password(self, user_id: str, new_password: str, current_password: str | None = None) -> bool: ...

    @abstractmethod
    def save_profile_photo(self, user_id: str, image: bytes) -> bool:
        """Kept on this computer only."""

    @abstractmethod
    def find_profile_photo(self, user_id: str) -> bytes | None: ...

    @abstractmethod
    def delete_profile_photo(self, user_id: str) -> bool: ...

    # ------------------------------------------------------------- projects (delegate to IProjectDAO)
    @abstractmethod
    def save_project(self, project: ProjectDTO) -> bool:
        """Write the project folder and remember where it is."""

    @abstractmethod
    def find_project_by_id(self, project_id: str) -> ProjectDTO | None: ...

    @abstractmethod
    def find_projects_by_user(self, user_id: str) -> list[ProjectDTO]:
        """Most recently opened first."""

    @abstractmethod
    def find_all_projects(self) -> list[ProjectDTO]: ...

    @abstractmethod
    def delete_project(self, project_id: str) -> bool:
        """Forget the project; its folder is kept."""

    @abstractmethod
    def load_project_folder(self, folder: str) -> ProjectDTO | None:
        """The project in ``folder``, or None if the folder is not a project."""

    @abstractmethod
    def move_project(self, project: ProjectDTO, new_folder: str) -> ProjectDTO: ...

    @abstractmethod
    def save_analysis_record(self, project: ProjectDTO, record: AnalysisRecordDTO) -> bool: ...

    @abstractmethod
    def find_analysis_records(self, project: ProjectDTO) -> list[AnalysisRecordDTO]:
        """Newest first."""
