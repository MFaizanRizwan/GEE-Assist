from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.dto.analysis_dto import AnalysisOptionDTO, AnalysisRequestDTO, ComputeDeviceDTO, FormulaDTO
from backend.dto.download_dto import DatasetDTO
from backend.dto.result_dto import ResultDTO


class IAnalysisService(ABC):
    """Class diagram: «interface» IAnalysisService (UC-06 Run Local Analysis)."""

    @abstractmethod
    def run_analysis(self, dataset: DatasetDTO, request: AnalysisRequestDTO,
                     on_progress: Optional[Callable[[float], None]] = None) -> ResultDTO: ...

    @abstractmethod
    def get_available_analyses(self, dataset: DatasetDTO) -> list[AnalysisOptionDTO]:
        """Every analysis category with its processes, and which this dataset can run."""

    @abstractmethod
    def save_result(self, result: ResultDTO, path: str) -> ResultDTO:
        """Keep a result: copy its GeoTIFF (and the .json of its numbers and settings) to ``path``."""

    @abstractmethod
    def discard_result(self, result: ResultDTO) -> None:
        """Delete a result that was not saved (its temporary files)."""

    @abstractmethod
    def list_saved_results(self, folder: str) -> list[ResultDTO]:
        """The analysis results saved in ``folder`` (a project's analysis folder), newest first."""

    @abstractmethod
    def load_result(self, path: str) -> ResultDTO:
        """A saved result GeoTIFF as a ResultDTO, from the settings and numbers saved next to it."""

    @abstractmethod
    def describe_dataset(self, path: str) -> DatasetDTO:
        """A GeoTIFF on disk as a dataset to analyse (its bands, satellite and dates)."""

    @abstractmethod
    def get_compute_device(self, use_gpu: bool = True) -> ComputeDeviceDTO:
        """Where analyses run (GPU or CPU), the graphics cards found and why."""

    @abstractmethod
    def list_formulas(self) -> list[FormulaDTO]: ...

    @abstractmethod
    def formula_categories(self) -> list[tuple[str, str]]: ...

    @abstractmethod
    def analysis_groups(self) -> list[tuple[str, str, str, tuple[str, ...]]]:
        """(analysis, label, what it is for, its sub-types) of the four analyses."""
