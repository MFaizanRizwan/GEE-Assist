from __future__ import annotations

from typing import Optional

from backend.data.clients.i_gee_client import IGEEClient, ProgressCallback, StopCheck
from backend.data.clients.i_gemini_client import IGeminiClient
from backend.data.clients.i_geocoding_client import IGeocodingClient
from backend.data.dao.formula_dao import FormulaDAO
from backend.data.dao.i_formula_dao import IFormulaDAO
from backend.data.i_data_facade import IDataFacade
from backend.dto import CheckDTO, ChunkDTO, FormDTO, PlaceDTO
from backend.dto.analysis_dto import FormulaDTO
from backend.dto.check_dto import CHECK_FAIL
from backend.exceptions import GEEError, PlaceSearchError

_NO_GEE = "Google Earth Engine is not set up in this build."


class DataFacade(IDataFacade):
    """Class diagram: DataFacade (-geminiClient, -geeClient, -userDAO, -projectDAO, -formulaDAO).

    The DAOs are wired in when persistence is built. The geocoding client looks up
    places by name for the AOI (not in the diagram, which predates place search).
    """

    def __init__(
        self,
        gemini_client: IGeminiClient,
        gee_client: Optional[IGEEClient] = None,
        user_dao=None,
        project_dao=None,
        formula_dao: Optional[IFormulaDAO] = None,
        geocoding_client: Optional[IGeocodingClient] = None,
    ):
        self._gemini_client = gemini_client
        self._gee_client = gee_client
        self._user_dao = user_dao
        self._project_dao = project_dao
        self._formula_dao = formula_dao or FormulaDAO()  # built into the app
        self._geocoding_client = geocoding_client

    def process_query(self, prompt: str) -> FormDTO:
        return self._gemini_client.process_query(prompt)

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

    def _gee(self) -> IGEEClient:
        if self._gee_client is None:
            raise GEEError(_NO_GEE)
        return self._gee_client
