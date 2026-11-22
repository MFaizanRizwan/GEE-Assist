from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from backend.business.analysis.i_analysis_service import IAnalysisService
from backend.business.download.i_download_service import IDownloadService
from backend.business.download.naming import parse_dataset_name
from backend.business.explanation.i_explanation_service import IExplanationService
from backend.business.facade.i_business_facade import IBusinessFacade
from backend.business.report.i_report_service import IReportService
from backend.business.map.i_map_service import IMapService
from backend.business.request.i_request_service import IRequestService
from backend.business.terrain.i_terrain_service import ITerrainService
from backend.business.vector.i_vector_service import IVectorService
from backend.business.settings.i_settings_service import ISettingsService
from backend.business.user.i_user_service import IUserService
from backend.dto import CheckDTO, DownloadJobDTO, FormDTO, PlaceDTO, ValidationDTO
from backend.dto.version_dto import AppVersionDTO
from backend.dto.analysis_dto import AnalysisOptionDTO, AnalysisRequestDTO, ComputeDeviceDTO, FormulaDTO
from backend.dto.download_dto import JOB_COMPLETED, DatasetDTO
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO
from backend.dto.map_dto import MapLayerDTO, RasterInfoDTO, RasterViewDTO, ViewPresetDTO
from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO
from backend.dto.report_dto import ExplanationFileDTO
from backend.dto.settings_dto import AppSettingsDTO, AppSettingsUpdateDTO
from backend.dto.result_dto import ResultDTO
from backend.dto.vector_dto import VectorLayerDTO
from backend.dto.terrain_dto import TerrainInfoDTO, TerrainProductDTO
from backend.exceptions import (
    AnalysisError,
    ExplanationError,
    GeeAssistError,
    ProjectError,
    ReportError,
    TerrainError,
    VectorError,
)
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


logger = logging.getLogger(__name__)

class BusinessFacade(IBusinessFacade):
    """Class diagram: BusinessFacade. Delegates to the services.

    Every service is injected here; optional ones raise a plain error when missing from a build.
    """

    def __init__(
        self,
        user_service: IUserService,
        request_service: IRequestService,
        download_service: IDownloadService,
        map_service: IMapService,
        analysis_service: Optional[IAnalysisService] = None,
        settings_service: ISettingsService | None = None,
        explanation_service: IExplanationService | None = None,
        report_service: IReportService | None = None,
        vector_service: IVectorService | None = None,
        terrain_service: ITerrainService | None = None,
    ):
        self._user_service = user_service
        self._request_service = request_service
        self._download_service = download_service
        self._map_service = map_service
        self._analysis_service = analysis_service
        self._settings_service = settings_service
        self._explanation_service = explanation_service
        self._report_service = report_service
        self._vector_service = vector_service
        self._terrain_service = terrain_service

    # ------------------------------------------------------------- authentication
    def is_server_available(self) -> bool:
        return self._user_service.is_server_available()

    def check_app_version(self) -> AppVersionDTO | None:
        return self._user_service.check_app_version()

    def get_current_user(self) -> UserDTO | None:
        return self._user_service.current_user

    def log_in(self, username: str, password: str, remember: bool = False) -> UserDTO:
        return self._user_service.log_in(username, password, remember)

    def restore_session(self) -> UserDTO | None:
        return self._user_service.restore_session()

    def reload_current_user(self) -> UserDTO:
        return self._user_service.reload_current_user()

    def get_session_info(self) -> SessionInfoDTO:
        return self._user_service.get_session_info()

    def log_out(self) -> None:
        self._user_service.log_out()
        self._request_service.close_project()  # the next user starts without one

    # ------------------------------------------------------------- app settings
    def get_app_settings(self) -> AppSettingsDTO:
        return self._settings().get_settings()

    def save_app_settings(self, update: AppSettingsUpdateDTO) -> ValidationDTO:
        return self._settings().save_settings(update)

    def _settings(self) -> ISettingsService:
        if self._settings_service is None:
            raise GeeAssistError("Settings are not set up in this build.")
        return self._settings_service

    def sign_up(self, data: SignupDTO) -> SignupResultDTO:
        return self._user_service.sign_up(data)

    def get_verification_status(self, verification_token: str) -> VerificationStatusDTO:
        return self._user_service.get_verification_status(verification_token)

    def resend_verification_email(self, verification_token: str, new_email: str | None = None) -> str:
        return self._user_service.resend_verification_email(verification_token, new_email)

    def start_google_sign_in(self) -> GoogleSignInDTO:
        return self._user_service.start_google_sign_in()

    def poll_google_sign_in(self, session_id: str, remember: bool = False) -> UserDTO | None:
        return self._user_service.poll_google_sign_in(session_id, remember)

    # ------------------------------------------------------------- user administration
    def list_users(self, skip: int = 0, limit: int = 50) -> UserPageDTO:
        return self._user_service.list_users(skip, limit)

    def get_user(self, user_id: str) -> UserDTO:
        return self._user_service.get_user(user_id)

    def set_user_role(self, user_id: str, role: str) -> UserDTO:
        return self._user_service.set_user_role(user_id, role)

    def set_user_active(self, user_id: str, is_active: bool) -> UserDTO:
        return self._user_service.set_user_active(user_id, is_active)

    def find_user_by_email(self, email: str) -> UserDTO | None:
        return self._user_service.find_user_by_email(email)

    def create_user(self, user: NewUserDTO) -> ValidationDTO:
        return self._user_service.create_user(user)

    def delete_user(self, user_id: str) -> bool:
        return self._user_service.delete_user(user_id)

    # ------------------------------------------------------------- forgot password
    def start_forgot_password(self, identifier: str) -> dict[str, Any]:
        return self._user_service.start_forgot_password(identifier)

    def poll_forgot_password(self, session_id: str) -> bool:
        return self._user_service.poll_forgot_password(session_id)

    def complete_forgot_password(
        self, session_id: str, new_password: str, confirm_password: str
    ) -> ValidationDTO:
        return self._user_service.complete_forgot_password(session_id, new_password, confirm_password)

    # ------------------------------------------------------------- manage account
    def update_user(self, user: UserDTO) -> ValidationDTO:
        return self._user_service.update_user(user)

    def change_password(
        self, user_id: str, new_password: str, confirm_password: str, current_password: str | None = None
    ) -> ValidationDTO:
        return self._user_service.change_password(user_id, new_password, confirm_password, current_password)

    def set_profile_photo(self, file_path: str) -> ValidationDTO:
        return self._user_service.set_profile_photo(file_path)

    def get_profile_photo(self, user_id: str | None = None) -> bytes | None:
        return self._user_service.get_profile_photo(user_id)

    def remove_profile_photo(self) -> bool:
        return self._user_service.remove_profile_photo()

    # ------------------------------------------------------------- query input
    def submit_query(self, text: str | None) -> FormDTO:
        return self._request_service.submit_query(text)

    def submit_form(self, form: FormDTO) -> ValidationDTO:
        return self._request_service.validate_form(form)

    def check_form(self, form: FormDTO) -> ValidationDTO:
        return self._request_service.check_form(form)

    def import_aoi(self, file_path: str) -> str:
        return self._request_service.import_aoi(file_path)

    def search_place(self, name: str) -> list[PlaceDTO]:
        return self._request_service.search_place(name)

    def get_kept_requests(self) -> list[FormDTO]:
        return self._request_service.get_kept_requests()

    # ------------------------------------------------------------- projects
    def save_project(self, project: ProjectDTO) -> bool:
        return self._request_service.save_project(project)

    def list_projects(self, user_id: str | None = None) -> list[ProjectDTO]:
        user_id = user_id if user_id is not None else self._user_id()
        return self._request_service.list_projects(user_id) if user_id else []

    def suggest_project_name(self, location: str) -> str:
        return self._request_service.suggest_project_name(location)

    def create_project(self, name: str, location: str) -> ProjectDTO:
        return self._request_service.create_project(name, location, self._user_id())

    def open_project(self, folder: str) -> ProjectDTO:
        return self._request_service.open_project(folder, self._user_id())

    def rename_project(self, new_name: str) -> ProjectDTO:
        return self._relocating(lambda: self._request_service.rename_project(new_name))

    def move_project(self, new_location: str) -> ProjectDTO:
        return self._relocating(lambda: self._request_service.move_project(new_location))

    def close_project(self) -> None:
        self._request_service.close_project()

    def get_current_project(self) -> ProjectDTO | None:
        return self._request_service.get_current_project()

    def get_analysis_results(self, project: ProjectDTO) -> list[AnalysisRecordDTO]:
        return self._request_service.get_analysis_results(project)

    def _relocating(self, change: Callable[[], ProjectDTO]) -> ProjectDTO:
        """Rename or move the open project; its saved downloads follow it."""
        before = self._request_service.get_current_project()
        if before is not None and self._download_service.is_busy_in(before.folder):
            raise ProjectError("A download in this project is running. Pause it, or let it finish, "
                               "before renaming or moving the project.")
        after = change()
        if before is not None and after.folder != before.folder:
            self._download_service.relocate(before.folder, after.folder)
        return after

    def _user_id(self) -> str:
        user = self._user_service.current_user
        return user.id if user is not None else ""

    def _require_project(self, why: str) -> ProjectDTO:
        project = self._request_service.get_current_project()
        if project is None:
            raise ProjectError(f"Create or open a project first: {why}")
        return project

    def _record(self, result: ResultDTO) -> None:
        """Keep the result in the open project's analysis_results.json; never lose the result over it."""
        if self._request_service.get_current_project() is None:
            return
        try:
            self._request_service.record_analysis_result(result)
        except GeeAssistError:
            logger.warning("Could not record the analysis result in the project", exc_info=True)

    # ------------------------------------------------------------- download (UC-05)
    def start_download(self, form: FormDTO) -> DownloadJobDTO:
        project = self._require_project("datasets are downloaded into the project's downloads folder.")
        return self._download_service.start_download(replace(form, output_dir=project.downloads_dir))

    def get_download_progress(self, job: DownloadJobDTO) -> DownloadJobDTO:
        return self._download_service.get_progress(job)

    def pause_download(self, job: DownloadJobDTO) -> DownloadJobDTO:
        return self._download_service.pause(job)

    def resume_download(self, job: DownloadJobDTO) -> DownloadJobDTO:
        return self._download_service.resume(job)

    def cancel_download(self, job: DownloadJobDTO) -> DownloadJobDTO:
        return self._download_service.cancel(job)

    def retry_failed_chunks(self, job: DownloadJobDTO) -> DownloadJobDTO:
        return self._download_service.retry_failed_chunks(job)

    def list_downloads(self) -> list[DownloadJobDTO]:
        return self._download_service.list_jobs()

    def save_download_copy(self, job: DownloadJobDTO, folder: str) -> str:
        return self._download_service.save_copy(job, folder)

    def get_chunk_size_mb(self) -> int:
        return self._download_service.chunk_size_mb()

    def set_chunk_size_mb(self, size_mb: int) -> int:
        return self._download_service.set_chunk_size_mb(size_mb)

    def is_gee_available(self) -> bool:
        return self._download_service.is_gee_available()

    def check_gee_setup(self) -> list[CheckDTO]:
        return self._download_service.check_gee_setup()

    def begin_gee_sign_in(self) -> str:
        return self._download_service.begin_gee_sign_in()

    def complete_gee_sign_in(self, should_stop: Optional[Callable[[], bool]] = None) -> str:
        return self._download_service.complete_gee_sign_in(should_stop)

    def cancel_gee_sign_in(self) -> None:
        self._download_service.cancel_gee_sign_in()

    def shutdown_downloads(self) -> None:
        self._download_service.shutdown()

    # ------------------------------------------------------------- viewing GeoTIFFs
    def describe_raster(self, path: str) -> RasterInfoDTO:
        return self._map_service.describe(path)

    def raster_view_presets(self, info: RasterInfoDTO, analysis_colours: bool = True) -> list[ViewPresetDTO]:
        return self._map_service.view_presets(info, analysis_colours)

    def render_raster(self, info: RasterInfoDTO, preset: ViewPresetDTO, max_size: int = 1600) -> RasterViewDTO:
        return self._map_service.render(info, preset, max_size)

    def raster_values_at(self, info: RasterInfoDTO, lon: float, lat: float) -> dict[str, float | None]:
        return self._map_service.values_at(info, lon, lat)

    # ------------------------------------------------------------- vector maps (shapefiles)
    def load_shapefile(self, path: str) -> VectorLayerDTO:
        return self._vector().load_shapefile(path)

    def _vector(self) -> IVectorService:
        if self._vector_service is None:
            raise VectorError("Vector maps are not set up in this build.")
        return self._vector_service

    # ------------------------------------------------------------- digital elevation model (DEM)
    def describe_dem(self, path: str) -> TerrainInfoDTO:
        return self._terrain().describe(path)

    def render_terrain(self, info: TerrainInfoDTO, product: str, params: dict | None = None,
                       max_size: int = 1600) -> TerrainProductDTO:
        return self._terrain().render(info, product, params, max_size)

    def save_terrain_product(self, info: TerrainInfoDTO, product: str, path: str,
                             params: dict | None = None) -> str:
        return self._terrain().save_product(info, product, path, params)

    def _terrain(self) -> ITerrainService:
        if self._terrain_service is None:
            raise TerrainError("The DEM tools are not set up in this build.")
        return self._terrain_service

    # ------------------------------------------------------------- analysis (UC-06)
    def list_formulas(self) -> list[FormulaDTO]:
        return self._analysis().list_formulas()

    def formula_categories(self) -> list[tuple[str, str]]:
        return self._analysis().formula_categories()

    def analysis_groups(self) -> list[tuple[str, str, str, tuple[str, ...]]]:
        return self._analysis().analysis_groups()

    def list_analysis_datasets(self) -> list[DatasetDTO]:
        """The open project's finished downloads; none when no project is open."""
        project = self._request_service.get_current_project()
        if project is None:
            return []
        folder = Path(project.folder).resolve()
        datasets = []
        jobs = sorted(self._download_service.list_jobs(), key=lambda job: job.finished_at or "", reverse=True)
        for job in jobs:
            if job.status != JOB_COMPLETED or job.dataset is None or not Path(job.dataset.path).is_file():
                continue
            if folder not in Path(job.dataset.path).resolve().parents:
                continue  # another project's download
            dataset = job.dataset
            satellite, start, end = parse_dataset_name(Path(dataset.path).stem)
            datasets.append(DatasetDTO(
                id=dataset.id, source=dataset.source, path=dataset.path, data_type=dataset.data_type,
                bands=list(dataset.bands), time_periods=dataset.time_periods, size_bytes=dataset.size_bytes,
                name=dataset.name or job.name, satellite=dataset.satellite or satellite,
                start_date=dataset.start_date or start, end_date=dataset.end_date or end,
            ))
        return datasets

    def describe_dataset(self, path: str) -> DatasetDTO:
        return self._analysis().describe_dataset(path)

    def get_available_analyses(self, dataset: DatasetDTO) -> list[AnalysisOptionDTO]:
        return self._analysis().get_available_analyses(dataset)

    def run_analysis(self, dataset: DatasetDTO, request: AnalysisRequestDTO,
                     on_progress: Optional[Callable[[float], None]] = None) -> ResultDTO:
        self._require_project("analysis results are kept in the project.")
        result = self._analysis().run_analysis(dataset, request, on_progress)
        self._record(result)
        return result

    def save_analysis_result(self, result: ResultDTO, path: str) -> ResultDTO:
        saved = self._analysis().save_result(result, path)
        self._record(saved)  # now with the saved file
        return saved

    def discard_analysis_result(self, result: ResultDTO) -> None:
        if self._analysis_service is not None:
            self._analysis_service.discard_result(result)

    def get_map_layers(self, result: ResultDTO, max_size: int = 1600) -> list[MapLayerDTO]:
        return self._map_service.build_layers(result, max_size)

    def get_compute_device(self, use_gpu: bool = True) -> ComputeDeviceDTO:
        return self._analysis().get_compute_device(use_gpu)

    def _analysis(self) -> IAnalysisService:
        if self._analysis_service is None:
            raise AnalysisError("Analysis is not set up in this build.")
        return self._analysis_service

    # ------------------------------------------------------------- AI explanation (UC-08)
    def list_saved_results(self) -> list[ResultDTO]:
        project = self._request_service.get_current_project()
        if project is None:
            return []
        return self._analysis().list_saved_results(project.analysis_dir)

    def prepare_explanation(self, result: ResultDTO) -> ExplanationRequestDTO:
        project = self._require_project("the result is saved in the project before it is sent to Gemini.")
        if not result.saved:  # the GeoTIFF sent to Gemini is always the one kept in the project
            target = free_path(Path(project.analysis_dir) / Path(result.output_path).name)
            result = self.save_analysis_result(result, str(target))
        return self._explanation().prepare(result)

    def explain_analysis_result(self, request: ExplanationRequestDTO) -> ExplanationDTO:
        project = self._require_project("the explanation is saved in the project's explanation folder.")
        return self._explanation().explain(request, project.explanation_dir)

    def _explanation(self) -> IExplanationService:
        if self._explanation_service is None:
            raise ExplanationError("AI explanations are not set up in this build.")
        return self._explanation_service

    # ------------------------------------------------------------- reports (UC-09)
    def list_explanations(self) -> list[ExplanationFileDTO]:
        project = self._request_service.get_current_project()
        return self._reports().list_explanations(project) if project is not None else []

    def create_report(self, explanation_path: str) -> str:
        project = self._require_project("reports are made from the project's explanations.")
        return self._reports().create_report(explanation_path, project)

    def export_report(self, pdf_path: str, destination: str) -> str:
        return self._reports().export_report(pdf_path, destination)

    def _reports(self) -> IReportService:
        if self._report_service is None:
            raise ReportError("Reports are not set up in this build.")
        return self._report_service


def free_path(path: Path) -> Path:
    """``path``, or ``<name>_2``, ``<name>_3``, ... when it is taken: an earlier result is never overwritten."""
    target, number = path, 2
    while target.exists():
        target = path.with_name(f"{path.stem}_{number}{path.suffix}")
        number += 1
    return target
