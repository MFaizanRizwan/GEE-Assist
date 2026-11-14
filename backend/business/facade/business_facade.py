from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from backend.business.analysis.i_analysis_service import IAnalysisService
from backend.business.download.i_download_service import IDownloadService
from backend.business.download.naming import parse_dataset_name
from backend.business.facade.i_business_facade import IBusinessFacade
from backend.business.map.i_map_service import IMapService
from backend.business.request.i_request_service import IRequestService
from backend.business.user.i_user_service import IUserService
from backend.dto import CheckDTO, DownloadJobDTO, FormDTO, PlaceDTO, ValidationDTO
from backend.dto.analysis_dto import AnalysisOptionDTO, AnalysisRequestDTO, ComputeDeviceDTO, FormulaDTO
from backend.dto.download_dto import JOB_COMPLETED, DatasetDTO
from backend.dto.map_dto import MapLayerDTO, RasterInfoDTO, RasterViewDTO, ViewPresetDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import AnalysisError
from backend.dto.user_dto import (
    GoogleSignInDTO,
    SessionInfoDTO,
    SignupDTO,
    SignupResultDTO,
    UserDTO,
    UserPageDTO,
    VerificationStatusDTO,
)


class BusinessFacade(IBusinessFacade):
    """Class diagram: BusinessFacade. Delegates to the services.

    Other services (analysis, explanation, report) are injected here as their use
    cases are implemented.
    """

    def __init__(
        self,
        user_service: IUserService,
        request_service: IRequestService,
        download_service: IDownloadService,
        map_service: IMapService,
        analysis_service: Optional[IAnalysisService] = None,
    ):
        self._user_service = user_service
        self._request_service = request_service
        self._download_service = download_service
        self._map_service = map_service
        self._analysis_service = analysis_service

    # ------------------------------------------------------------- authentication
    def is_server_available(self) -> bool:
        return self._user_service.is_server_available()

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

    # ------------------------------------------------------------- query input
    def submit_query(self, text: str) -> FormDTO:
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

    # ------------------------------------------------------------- download (UC-05)
    def start_download(self, form: FormDTO) -> DownloadJobDTO:
        return self._download_service.start_download(form)

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

    def raster_view_presets(self, info: RasterInfoDTO) -> list[ViewPresetDTO]:
        return self._map_service.view_presets(info)

    def render_raster(self, info: RasterInfoDTO, preset: ViewPresetDTO, max_size: int = 1600) -> RasterViewDTO:
        return self._map_service.render(info, preset, max_size)

    def raster_values_at(self, info: RasterInfoDTO, lon: float, lat: float) -> dict[str, float | None]:
        return self._map_service.values_at(info, lon, lat)

    # ------------------------------------------------------------- analysis (UC-06)
    def list_formulas(self) -> list[FormulaDTO]:
        return self._analysis().list_formulas()

    def formula_categories(self) -> list[tuple[str, str]]:
        return self._analysis().formula_categories()

    def analysis_groups(self) -> list[tuple[str, str, str, tuple[str, ...]]]:
        return self._analysis().analysis_groups()

    def list_analysis_datasets(self) -> list[DatasetDTO]:
        datasets = []
        jobs = sorted(self._download_service.list_jobs(), key=lambda job: job.finished_at or "", reverse=True)
        for job in jobs:
            if job.status != JOB_COMPLETED or job.dataset is None or not Path(job.dataset.path).is_file():
                continue
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
        return self._analysis().run_analysis(dataset, request, on_progress)

    def get_map_layers(self, result: ResultDTO, max_size: int = 1600) -> list[MapLayerDTO]:
        return self._map_service.build_layers(result, max_size)

    def get_compute_device(self, use_gpu: bool = True) -> ComputeDeviceDTO:
        return self._analysis().get_compute_device(use_gpu)

    def _analysis(self) -> IAnalysisService:
        if self._analysis_service is None:
            raise AnalysisError("Analysis is not set up in this build.")
        return self._analysis_service
