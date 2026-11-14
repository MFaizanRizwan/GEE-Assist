from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.dto.analysis_dto import AnalysisConfigDTO, ProcessOptionDTO
from backend.dto.download_dto import DatasetDTO
from backend.dto.result_dto import ResultDTO


class IAnalysis(ABC):
    """Class diagram: «interface» IAnalysis. One analysis category (water, vegetation, ...).

    ``run``'s ``params`` holds the user's parameters (e.g. ``savi_l``) and these
    reserved keys, set by ``AnalysisService``:

    * ``_compare_with``: list[DatasetDTO], the other time periods;
    * ``_backend``: the ComputeBackend (GPU or CPU) to compute with;
    * ``_output_path``: where to write the result GeoTIFF;
    * ``_on_progress``: called with 0-1 while it runs.
    """

    @abstractmethod
    def configure(self, config: AnalysisConfigDTO) -> None: ...

    @abstractmethod
    def list_available(self, dataset: DatasetDTO) -> list[str]:
        """The processes this dataset's bands can compute."""

    @abstractmethod
    def process_options(self, dataset: DatasetDTO) -> list[ProcessOptionDTO]:
        """Every process, with whether this dataset can run it and, if not, why."""

    @abstractmethod
    def run(self, processes: list[str], dataset: DatasetDTO, params: dict[str, Any]) -> ResultDTO: ...

    @abstractmethod
    def get_category(self) -> str: ...
