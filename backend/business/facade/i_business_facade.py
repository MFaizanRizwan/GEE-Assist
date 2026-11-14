from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.dto import CheckDTO, DownloadJobDTO, FormDTO, PlaceDTO, ValidationDTO
from backend.dto.analysis_dto import AnalysisOptionDTO, AnalysisRequestDTO, ComputeDeviceDTO, FormulaDTO
from backend.dto.download_dto import DatasetDTO
from backend.dto.map_dto import MapLayerDTO, RasterInfoDTO, RasterViewDTO, ViewPresetDTO
from backend.dto.result_dto import ResultDTO
from backend.dto.user_dto import (
    GoogleSignInDTO,
    SessionInfoDTO,
    SignupDTO,
    SignupResultDTO,
    UserDTO,
    UserPageDTO,
    VerificationStatusDTO,
)


class IBusinessFacade(ABC):
    """Class diagram: IBusinessFacade. The only backend entry point the UI uses.

    The authentication, query-input and download operations exist so far; the other
    use cases (analysis, maps, ...) add their methods here.
    """

    # ------------------------------------------------------------- authentication
    @abstractmethod
    def is_server_available(self) -> bool: ...

    @abstractmethod
    def get_current_user(self) -> UserDTO | None: ...

    @abstractmethod
    def log_in(self, username: str, password: str, remember: bool = False) -> UserDTO: ...

    @abstractmethod
    def restore_session(self) -> UserDTO | None: ...

    @abstractmethod
    def reload_current_user(self) -> UserDTO: ...

    @abstractmethod
    def get_session_info(self) -> SessionInfoDTO: ...

    @abstractmethod
    def log_out(self) -> None: ...

    @abstractmethod
    def sign_up(self, data: SignupDTO) -> SignupResultDTO: ...

    @abstractmethod
    def get_verification_status(self, verification_token: str) -> VerificationStatusDTO: ...

    @abstractmethod
    def resend_verification_email(self, verification_token: str, new_email: str | None = None) -> str: ...

    @abstractmethod
    def start_google_sign_in(self) -> GoogleSignInDTO: ...

    @abstractmethod
    def poll_google_sign_in(self, session_id: str, remember: bool = False) -> UserDTO | None: ...

    # ------------------------------------------------------------- user administration
    @abstractmethod
    def list_users(self, skip: int = 0, limit: int = 50) -> UserPageDTO: ...

    @abstractmethod
    def get_user(self, user_id: str) -> UserDTO: ...

    @abstractmethod
    def set_user_role(self, user_id: str, role: str) -> UserDTO: ...

    @abstractmethod
    def set_user_active(self, user_id: str, is_active: bool) -> UserDTO: ...

    # ------------------------------------------------------------- query input
    @abstractmethod
    def submit_query(self, text: str) -> FormDTO: ...

    @abstractmethod
    def submit_form(self, form: FormDTO) -> ValidationDTO: ...

    @abstractmethod
    def check_form(self, form: FormDTO) -> ValidationDTO:
        """Validate the parameters without keeping them."""

    @abstractmethod
    def import_aoi(self, file_path: str) -> str: ...

    @abstractmethod
    def search_place(self, name: str) -> list[PlaceDTO]:
        """Find a city, region or country by name; each match's ``aoi`` is its exact boundary."""

    @abstractmethod
    def get_kept_requests(self) -> list[FormDTO]: ...

    # ------------------------------------------------------------- download (UC-05)
    @abstractmethod
    def start_download(self, form: FormDTO) -> DownloadJobDTO: ...

    @abstractmethod
    def get_download_progress(self, job: DownloadJobDTO) -> DownloadJobDTO: ...

    @abstractmethod
    def pause_download(self, job: DownloadJobDTO) -> DownloadJobDTO: ...

    @abstractmethod
    def resume_download(self, job: DownloadJobDTO) -> DownloadJobDTO: ...

    @abstractmethod
    def cancel_download(self, job: DownloadJobDTO) -> DownloadJobDTO: ...

    @abstractmethod
    def retry_failed_chunks(self, job: DownloadJobDTO) -> DownloadJobDTO: ...

    @abstractmethod
    def list_downloads(self) -> list[DownloadJobDTO]: ...

    @abstractmethod
    def get_chunk_size_mb(self) -> int: ...

    @abstractmethod
    def set_chunk_size_mb(self, size_mb: int) -> int: ...

    @abstractmethod
    def is_gee_available(self) -> bool: ...

    @abstractmethod
    def check_gee_setup(self) -> list[CheckDTO]:
        """The Earth Engine set-up checked step by step: library, project, sign-in, connection, test request."""

    @abstractmethod
    def begin_gee_sign_in(self) -> str:
        """Start signing this computer in to Earth Engine; returns the Google page to open in the browser."""

    @abstractmethod
    def complete_gee_sign_in(self, should_stop: Optional[Callable[[], bool]] = None) -> str:
        """Wait for the browser to come back from Google; returns the file the sign-in was saved in."""

    @abstractmethod
    def cancel_gee_sign_in(self) -> None: ...

    @abstractmethod
    def shutdown_downloads(self) -> None:
        """Called when the app closes: the active download is paused and resumes next time."""

    # ------------------------------------------------------------- viewing GeoTIFFs
    @abstractmethod
    def describe_raster(self, path: str) -> RasterInfoDTO: ...

    @abstractmethod
    def raster_view_presets(self, info: RasterInfoDTO) -> list[ViewPresetDTO]: ...

    @abstractmethod
    def render_raster(self, info: RasterInfoDTO, preset: ViewPresetDTO, max_size: int = 1600) -> RasterViewDTO: ...

    @abstractmethod
    def raster_values_at(self, info: RasterInfoDTO, lon: float, lat: float) -> dict[str, float | None]: ...

    # ------------------------------------------------------------- analysis (UC-06) and its formula table
    @abstractmethod
    def list_formulas(self) -> list[FormulaDTO]:
        """Every spectral index and method, with its formula and use cases (the analysis table)."""

    @abstractmethod
    def formula_categories(self) -> list[tuple[str, str]]:
        """(sub-type, what it is for), in display order."""

    @abstractmethod
    def analysis_groups(self) -> list[tuple[str, str, str, tuple[str, ...]]]:
        """(analysis, label, what it is for, its sub-types) of the four analyses: water, vegetation, LST, LULC."""

    @abstractmethod
    def list_analysis_datasets(self) -> list[DatasetDTO]:
        """Finished downloads whose GeoTIFF is still on disk, newest first."""

    @abstractmethod
    def describe_dataset(self, path: str) -> DatasetDTO:
        """Any GeoTIFF on the computer as a dataset to analyse."""

    @abstractmethod
    def get_available_analyses(self, dataset: DatasetDTO) -> list[AnalysisOptionDTO]: ...

    @abstractmethod
    def run_analysis(self, dataset: DatasetDTO, request: AnalysisRequestDTO,
                     on_progress: Optional[Callable[[float], None]] = None) -> ResultDTO: ...

    @abstractmethod
    def get_map_layers(self, result: ResultDTO, max_size: int = 1600) -> list[MapLayerDTO]:
        """Each layer of an analysis result drawn and ready to show."""

    @abstractmethod
    def get_compute_device(self, use_gpu: bool = True) -> ComputeDeviceDTO:
        """Where analyses run (GPU or CPU), the graphics cards found, and why."""
