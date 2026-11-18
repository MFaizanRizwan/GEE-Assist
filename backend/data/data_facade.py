from __future__ import annotations

from typing import Optional

from backend.auth_exceptions import AuthError
from backend.config.settings import PROJECT_HISTORY_FILE
from backend.data.clients.i_gee_client import IGEEClient, ProgressCallback, StopCheck
from backend.data.clients.i_gemini_client import IGeminiClient
from backend.data.clients.i_geocoding_client import IGeocodingClient
from backend.data.dao.formula_dao import FormulaDAO
from backend.data.dao.project_dao import ProjectDAO
from backend.data.dao.i_formula_dao import IFormulaDAO
from backend.data.dao.i_project_dao import IProjectDAO
from backend.data.dao.i_user_dao import IUserDAO
from backend.data.i_data_facade import IDataFacade
from backend.dto import CheckDTO, ChunkDTO, FormDTO, PlaceDTO
from backend.dto.analysis_dto import FormulaDTO
from backend.dto.check_dto import CHECK_FAIL
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO
from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO
from backend.dto.user_dto import NewUserDTO, UserDTO, UserPageDTO
from backend.exceptions import GEEError, PlaceSearchError

_NO_GEE = "Google Earth Engine is not set up in this build."
_NO_USERS = "User accounts are not set up in this build."


class DataFacade(IDataFacade):
    """Class diagram: DataFacade (-geminiClient, -geeClient, -userDAO, -projectDAO, -formulaDAO).

    The DAOs are wired in when persistence is built. The geocoding client looks up
    places by name for the AOI (not in the diagram, which predates place search).
    """

    def __init__(
        self,
        gemini_client: IGeminiClient,
        gee_client: Optional[IGEEClient] = None,
        user_dao: Optional[IUserDAO] = None,
        project_dao: Optional[IProjectDAO] = None,
        formula_dao: Optional[IFormulaDAO] = None,
        geocoding_client: Optional[IGeocodingClient] = None,
    ):
        self._gemini_client = gemini_client
        self._gee_client = gee_client
        self._user_dao = user_dao
        self._project_dao = project_dao or ProjectDAO(PROJECT_HISTORY_FILE)  # folders on this computer
        self._formula_dao = formula_dao or FormulaDAO()  # built into the app
        self._geocoding_client = geocoding_client

    def process_query(self, prompt: str) -> FormDTO:
        return self._gemini_client.process_query(prompt)

    def generate_explanation(self, request: ExplanationRequestDTO) -> ExplanationDTO:
        return self._gemini_client.generate_explanation(request)

    def search_places(self, query: str) -> list[PlaceDTO]:
        if self._geocoding_client is None:
            raise PlaceSearchError("Place search is not set up in this build. Draw the area on the map instead.")
        return self._geocoding_client.search(query)

    def fetch_chunk(
        self,
        chunk: ChunkDTO,
        path: str,
        on_progress: Optional[ProgressCallback] = None,
        should_stop: Optional[StopCheck] = None,
    ) -> bool:
        return self._gee().fetch_chunk(chunk, path, on_progress, should_stop)

    def configure_gee_project(self, project: str) -> None:
        if self._gee_client is not None:
            self._gee_client.set_project(project)

    def configure_gemini_key(self, api_key: str) -> None:
        if self._gemini_client is not None:
            self._gemini_client.set_api_key(api_key)

    def validate_access(self) -> bool:
        return self._gee_client is not None and self._gee_client.validate_access()

    def diagnose_gee(self) -> list[CheckDTO]:
        if self._gee_client is None:
            return [CheckDTO("Earth Engine", CHECK_FAIL, _NO_GEE)]
        return self._gee_client.diagnose()

    def begin_gee_sign_in(self) -> str:
        return self._gee().begin_sign_in()

    def complete_gee_sign_in(self, should_stop: Optional[StopCheck] = None) -> str:
        return self._gee().complete_sign_in(should_stop)

    def cancel_gee_sign_in(self) -> None:
        if self._gee_client is not None:
            self._gee_client.cancel_sign_in()

    def list_formulas(self) -> list[FormulaDTO]:
        return self._formula_dao.find_all()

    def get_formula(self, key: str) -> FormulaDTO | None:
        return self._formula_dao.find_by_key(key)

    def formula_categories(self) -> list[tuple[str, str]]:
        return self._formula_dao.categories()

    def analysis_groups(self) -> list[tuple[str, str, str, tuple[str, ...]]]:
        return self._formula_dao.analyses()

    # ------------------------------------------------------------- user accounts
    def save_user(self, user: UserDTO) -> UserDTO:
        return self._users().save(user)

    def find_user_by_id(self, user_id: str) -> UserDTO | None:
        return self._users().find_by_id(user_id)

    def find_user_by_email(self, email: str) -> UserDTO | None:
        return self._users().find_by_email(email)

    def find_users(self, skip: int = 0, limit: int = 50) -> UserPageDTO:
        return self._users().find_all(skip, limit)

    def delete_user(self, user_id: str) -> bool:
        return self._users().delete(user_id)

    def create_user(self, user: NewUserDTO) -> UserDTO:
        return self._users().create(user)

    def change_password(self, user_id: str, new_password: str, current_password: str | None = None) -> bool:
        return self._users().change_password(user_id, new_password, current_password)

    def save_profile_photo(self, user_id: str, image: bytes) -> bool:
        return self._users().save_photo(user_id, image)

    def find_profile_photo(self, user_id: str) -> bytes | None:
        return self._users().find_photo(user_id)

    def delete_profile_photo(self, user_id: str) -> bool:
        return self._users().delete_photo(user_id)

    # ------------------------------------------------------------- projects
    def save_project(self, project: ProjectDTO) -> bool:
        return self._project_dao.save(project)

    def find_project_by_id(self, project_id: str) -> ProjectDTO | None:
        return self._project_dao.find_by_id(project_id)

    def find_projects_by_user(self, user_id: str) -> list[ProjectDTO]:
        return self._project_dao.find_by_user_id(user_id)

    def find_all_projects(self) -> list[ProjectDTO]:
        return self._project_dao.find_all()

    def delete_project(self, project_id: str) -> bool:
        return self._project_dao.delete(project_id)

    def load_project_folder(self, folder: str) -> ProjectDTO | None:
        return self._project_dao.load_folder(folder)

    def move_project(self, project: ProjectDTO, new_folder: str) -> ProjectDTO:
        return self._project_dao.move(project, new_folder)

    def save_analysis_record(self, project: ProjectDTO, record: AnalysisRecordDTO) -> bool:
        return self._project_dao.save_analysis_result(project, record)

    def find_analysis_records(self, project: ProjectDTO) -> list[AnalysisRecordDTO]:
        return self._project_dao.find_analysis_results(project)

    def _users(self) -> IUserDAO:
        if self._user_dao is None:
            raise AuthError(_NO_USERS)
        return self._user_dao

    def _gee(self) -> IGEEClient:
        if self._gee_client is None:
            raise GEEError(_NO_GEE)
        return self._gee_client
