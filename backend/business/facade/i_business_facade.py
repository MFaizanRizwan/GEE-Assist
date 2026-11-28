from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.dto import CheckDTO, DownloadJobDTO, FormDTO, PlaceDTO, ValidationDTO
from backend.dto.version_dto import AppVersionDTO
from backend.dto.analysis_dto import AnalysisOptionDTO, AnalysisRequestDTO, ComputeDeviceDTO, FormulaDTO
from backend.dto.download_dto import DatasetDTO
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO
from backend.dto.map_dto import MapLayerDTO, RasterInfoDTO, RasterViewDTO, ViewPresetDTO
from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO
from backend.dto.report_dto import ExplanationFileDTO
from backend.dto.settings_dto import AppSettingsDTO, AppSettingsUpdateDTO
from backend.dto.result_dto import ResultDTO
from backend.dto.vector_dto import VectorLayerDTO
from backend.dto.terrain_dto import TerrainInfoDTO, TerrainProductDTO
from backend.dto.interpolation_dto import IDWParamsDTO, IDWResultDTO, SamplePointDTO
from backend.dto.prediction_dto import (
    AlgorithmDTO,
    PredictionProgress,
    PredictionRequestDTO,
    PredictionResultDTO,
    RasterBandsDTO,
)
from backend.dto.catalog_dto import CatalogRequestDTO, CatalogResultDTO, CatalogSourceDTO
from backend.dto.user_dto import (
    GoogleSignInDTO,
    NewUserDTO,
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
    def check_app_version(self) -> AppVersionDTO | None: ...

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

    # ------------------------------------------------------------- app settings
    @abstractmethod
    def get_app_settings(self) -> AppSettingsDTO:
        """The Earth Engine project, whether a Gemini key is set, and the "Keep me signed in" length."""

    @abstractmethod
    def save_app_settings(self, update: AppSettingsUpdateDTO) -> ValidationDTO:
        """Save them on this computer and use them at once; field problems come back in ``errors``."""

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

    @abstractmethod
    def find_user_by_email(self, email: str) -> UserDTO | None: ...

    @abstractmethod
    def create_user(self, user: NewUserDTO) -> ValidationDTO: ...

    @abstractmethod
    def delete_user(self, user_id: str) -> bool: ...

    # ------------------------------------------------------------- forgot password
    @abstractmethod
    def start_forgot_password(self, identifier: str) -> dict[str, Any]: ...

    @abstractmethod
    def poll_forgot_password(self, session_id: str) -> bool: ...

    @abstractmethod
    def complete_forgot_password(
        self, session_id: str, new_password: str, confirm_password: str
    ) -> ValidationDTO: ...

    # ------------------------------------------------------------- manage account
    @abstractmethod
    def update_user(self, user: UserDTO) -> ValidationDTO:
        """Save changed details (your own, or anyone's for an admin); field problems come back in ``errors``."""

    @abstractmethod
    def change_password(
        self, user_id: str, new_password: str, confirm_password: str, current_password: str | None = None
    ) -> ValidationDTO: ...

    @abstractmethod
    def set_profile_photo(self, file_path: str) -> ValidationDTO:
        """The signed-in user's photo, kept on this computer only."""

    @abstractmethod
    def get_profile_photo(self, user_id: str | None = None) -> bytes | None: ...

    @abstractmethod
    def remove_profile_photo(self) -> bool: ...

    # ------------------------------------------------------------- query input
    @abstractmethod
    def submit_query(self, text: str | None) -> FormDTO: ...

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

    # ------------------------------------------------------------- projects
    @abstractmethod
    def save_project(self, project: ProjectDTO) -> bool: ...

    @abstractmethod
    def list_projects(self, user_id: str | None = None) -> list[ProjectDTO]:
        """The user's projects (the signed-in user's by default), most recently opened first."""

    @abstractmethod
    def suggest_project_name(self, location: str) -> str:
        """The name a new project in ``location`` gets when none is typed: Project 1, Project 2, ..."""

    @abstractmethod
    def create_project(self, name: str, location: str) -> ProjectDTO:
        """Make ``<location>/<name>`` with ``downloads/`` and ``analysis/`` folders, and open it."""

    @abstractmethod
    def open_project(self, folder: str) -> ProjectDTO: ...

    @abstractmethod
    def rename_project(self, new_name: str) -> ProjectDTO:
        """Rename the open project and its folder (not while one of its downloads is running)."""

    @abstractmethod
    def move_project(self, new_location: str) -> ProjectDTO:
        """Move the open project's folder (not while one of its downloads is running)."""

    @abstractmethod
    def close_project(self) -> None: ...

    @abstractmethod
    def get_current_project(self) -> ProjectDTO | None: ...

    @abstractmethod
    def get_analysis_results(self, project: ProjectDTO) -> list[AnalysisRecordDTO]:
        """The project's analysis results, newest first."""

    # ------------------------------------------------------------- download (UC-05)
    @abstractmethod
    def start_download(self, form: FormDTO) -> DownloadJobDTO:
        """Download into the open project's downloads folder. ProjectError if no project is open."""

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
    def save_download_copy(self, job: DownloadJobDTO, folder: str) -> str:
        """Copy a finished download's GeoTIFF into a folder the user chose; returns the copy's path."""

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
    def raster_view_presets(self, info: RasterInfoDTO, analysis_colours: bool = True) -> list[ViewPresetDTO]:
        """The ways to show the file. ``analysis_colours``: an analysis result's layers as on the Analysis page."""

    @abstractmethod
    def render_raster(self, info: RasterInfoDTO, preset: ViewPresetDTO, max_size: int = 1600) -> RasterViewDTO: ...

    @abstractmethod
    def raster_values_at(self, info: RasterInfoDTO, lon: float, lat: float) -> dict[str, float | None]: ...

    # ------------------------------------------------------------- vector maps (shapefiles)
    @abstractmethod
    def load_shapefile(self, path: str) -> VectorLayerDTO:
        """Read a shapefile (.shp) and reproject it to WGS84 for the Vector Maps page."""

    @abstractmethod
    def vector_rings_in_crs(self, layer: VectorLayerDTO, crs: str) -> list[list[tuple[float, float]]]:
        """A loaded layer's rings in another coordinate system (to draw it over a projected raster)."""

    # ------------------------------------------------------------- digital elevation model (DEM)
    @abstractmethod
    def describe_dem(self, path: str) -> TerrainInfoDTO:
        """Read a DEM GeoTIFF's details (extent, cell size, elevation range) for the DEM page."""

    @abstractmethod
    def render_terrain(self, info: TerrainInfoDTO, product: str, params: dict | None = None,
                       max_size: int = 1600) -> TerrainProductDTO:
        """Draw a derived surface: elevation (shaded relief), hillshade, slope, aspect or contours."""

    @abstractmethod
    def save_terrain_product(self, info: TerrainInfoDTO, product: str, path: str,
                             params: dict | None = None) -> str:
        """Write a derived surface as a GeoTIFF at the DEM's full resolution; returns its path."""

    # ------------------------------------------------------------- IDW interpolation
    @abstractmethod
    def interpolate_idw(self, points, field: str, params: IDWParamsDTO | None = None) -> IDWResultDTO:
        """Interpolate sample points (SamplePointDTO) into an inverse-distance-weighted raster surface."""

    @abstractmethod
    def save_interpolation(self, result: IDWResultDTO, path: str) -> str:
        """Write an interpolated surface as a GeoTIFF (EPSG:4326); returns its path."""

    @abstractmethod
    def inspect_points_csv(self, path: str):
        """A CSV of sample points: its columns and the longitude / latitude columns guessed."""

    @abstractmethod
    def load_points_csv(self, path: str, lon_column: str = "", lat_column: str = "") -> VectorLayerDTO:
        """A CSV's rows as a point layer (WGS84 degrees), for IDW."""

    # ------------------------------------------------------------- machine-learning prediction
    @abstractmethod
    def prediction_algorithms(self, task: str) -> list[AlgorithmDTO]:
        """The algorithms offered for a prediction task, with whether each can run here."""

    @abstractmethod
    def describe_prediction_input(self, path: str) -> RasterBandsDTO:
        """A GeoTIFF's bands and the date its name suggests, for the Prediction page."""

    @abstractmethod
    def run_prediction(self, request: PredictionRequestDTO,
                       progress: PredictionProgress | None = None) -> PredictionResultDTO:
        """Train, score and rank the chosen algorithms on past and present data, and predict."""

    @abstractmethod
    def save_prediction(self, result: PredictionResultDTO, path: str, key: str = "") -> str:
        """Write a prediction (the best model's, or ``key``'s) as a GeoTIFF; returns its path."""

    # ------------------------------------------------------------- data catalog (downloading datasets)
    @abstractmethod
    def list_data_sources(self) -> list[CatalogSourceDTO]:
        """The data providers (Earth Engine, Natural Earth, Geofabrik, HDX) and their choices."""

    @abstractmethod
    def download_dataset(self, request: CatalogRequestDTO, dest_dir: str,
                         on_progress=None) -> CatalogResultDTO:
        """Download a dataset from a provider into a fresh folder under ``dest_dir``."""

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
        """The open project's finished downloads whose GeoTIFF is still on disk, newest first
        (none when no project is open)."""

    @abstractmethod
    def describe_dataset(self, path: str) -> DatasetDTO:
        """Any GeoTIFF on the computer as a dataset to analyse."""

    @abstractmethod
    def get_available_analyses(self, dataset: DatasetDTO) -> list[AnalysisOptionDTO]: ...

    @abstractmethod
    def run_analysis(self, dataset: DatasetDTO, request: AnalysisRequestDTO,
                     on_progress: Optional[Callable[[float], None]] = None) -> ResultDTO: ...

    @abstractmethod
    def save_analysis_result(self, result: ResultDTO, path: str) -> ResultDTO:
        """Keep a result where the user chose (only saved results stay on disk); returns it at its new place."""

    @abstractmethod
    def discard_analysis_result(self, result: ResultDTO) -> None:
        """Delete a result the user did not save."""

    @abstractmethod
    def get_map_layers(self, result: ResultDTO, max_size: int = 1600) -> list[MapLayerDTO]:
        """Each layer of an analysis result drawn and ready to show."""

    @abstractmethod
    def get_compute_device(self, use_gpu: bool = True) -> ComputeDeviceDTO:
        """Where analyses run (GPU or CPU), the graphics cards found, and why."""

    # ------------------------------------------------------------- AI explanation (UC-08)
    @abstractmethod
    def list_saved_results(self) -> list[ResultDTO]:
        """The analysis results (GeoTIFFs) saved in the open project's analysis folder, newest first;
        none when no project is open. Each can be explained with ``prepare_explanation``."""

    @abstractmethod
    def prepare_explanation(self, result: ResultDTO) -> ExplanationRequestDTO:
        """Save the result's GeoTIFF in the open project's analysis folder (if it is not saved yet),
        then gather what Gemini is given: the analysis, the metadata before and after it, its numbers
        and a preview of each layer. The request's ``result`` is the saved result."""

    @abstractmethod
    def explain_analysis_result(self, request: ExplanationRequestDTO) -> ExplanationDTO:
        """Send the saved GeoTIFF, previews and prompt to Gemini; its answer is kept in the open
        project's ``explanation`` folder."""

    # ------------------------------------------------------------- reports (UC-09)
    @abstractmethod
    def list_explanations(self) -> list[ExplanationFileDTO]:
        """The AI explanations saved in the open project, newest first; none when no project is open."""

    @abstractmethod
    def create_report(self, explanation_path: str) -> str:
        """Write a saved explanation's PDF report (the analysis pictures, then the explanation) in the
        open project's reports folder; returns its path."""

    @abstractmethod
    def export_report(self, pdf_path: str, destination: str) -> str:
        """Copy a report's PDF to a file the user chose on this computer; returns where it went."""
