"""Class diagram: AnalysisService (-dataFacade: IDataFacade, -analyses: list[IAnalysis]).

Each analysis is configured with its category's formulas from the formula DAO (through
the data facade). Before every run the compute device is chosen: a dedicated NVIDIA
GPU through CuPy when there is one that works, otherwise the CPU.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from backend.business.analysis.base_analysis import read_band_names
from backend.business.analysis.burn_analysis import BurnAnalysis
from backend.business.analysis.compute_device import ComputeBackend, cached_gpus, select_backend
from backend.business.analysis.i_analysis import IAnalysis
from backend.business.analysis.i_analysis_service import IAnalysisService
from backend.business.analysis.lst_analysis import LSTAnalysis
from backend.business.analysis.lulc_analysis import LULCAnalysis
from backend.business.analysis.moisture_analysis import MoistureAnalysis
from backend.business.analysis.sar_analysis import SARAnalysis
from backend.business.analysis.sensors import resolve_satellite
from backend.business.analysis.snow_analysis import SnowAnalysis
from backend.business.analysis.soil_analysis import SoilAnalysis
from backend.business.analysis.transformation_analysis import TransformationAnalysis
from backend.business.analysis.urban_analysis import UrbanAnalysis
from backend.business.analysis.vegetation_analysis import VegetationAnalysis
from backend.business.analysis.water_analysis import WaterAnalysis
from backend.business.download.naming import parse_dataset_name
from backend.data.i_data_facade import IDataFacade
from backend.dto.analysis_dto import (
    AnalysisConfigDTO,
    AnalysisOptionDTO,
    AnalysisRequestDTO,
    ComputeDeviceDTO,
    FormulaDTO,
    GpuDTO,
)
from backend.dto.download_dto import DatasetDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import AnalysisError


def default_analyses() -> list[IAnalysis]:
    return [VegetationAnalysis(), MoistureAnalysis(), WaterAnalysis(), BurnAnalysis(), SoilAnalysis(),
            UrbanAnalysis(), SnowAnalysis(), LSTAnalysis(), LULCAnalysis(), TransformationAnalysis(), SARAnalysis()]


class AnalysisService(IAnalysisService):
    def __init__(
        self,
        data_facade: IDataFacade,
        analyses: Optional[list[IAnalysis]] = None,
        find_gpus: Callable[[], tuple[GpuDTO, ...]] = cached_gpus,
        select: Callable[..., ComputeBackend] = select_backend,
        block_rows: int = 1024,
    ):
        self._data_facade = data_facade
        self._find_gpus = find_gpus
        self._select = select
        self._descriptions = dict(data_facade.formula_categories())
        formulas = data_facade.list_formulas()
        self._analyses: list[IAnalysis] = analyses if analyses is not None else default_analyses()
        for analysis in self._analyses:
            category = analysis.get_category()
            mine = tuple(formula for formula in formulas if formula.category == category)
            analysis.configure(AnalysisConfigDTO(category, mine, block_rows=block_rows))
        order = {category: index for index, category in enumerate(self._descriptions)}
        self._analyses.sort(key=lambda analysis: order.get(analysis.get_category(), len(order)))

    # ------------------------------------------------------------- IAnalysisService
    def get_available_analyses(self, dataset: DatasetDTO) -> list[AnalysisOptionDTO]:
        return [AnalysisOptionDTO(analysis.get_category(), self._descriptions.get(analysis.get_category(), ""),
                                  tuple(analysis.process_options(dataset)))
                for analysis in self._analyses]

    def run_analysis(self, dataset: DatasetDTO, request: AnalysisRequestDTO,
                     on_progress: Optional[Callable[[float], None]] = None) -> ResultDTO:
        analysis = self._analysis(request.category)
        backend = self._backend(request.use_gpu)
        params: dict[str, Any] = dict(request.params)
        params.update(_compare_with=list(request.compare_with), _backend=backend, _on_progress=on_progress)
        if request.output_dir and hasattr(analysis, "default_output"):
            params["_output_path"] = str(Path(request.output_dir) / analysis.default_output(dataset).name)
        return analysis.run(list(request.processes), dataset, params)

    def describe_dataset(self, path: str) -> DatasetDTO:
        file = Path(path)
        names = read_band_names(path)
        satellite, start, end = parse_dataset_name(file.stem)
        dataset = DatasetDTO(id="", source="", path=str(file), bands=list(names),
                             size_bytes=file.stat().st_size if file.exists() else 0, name=file.stem,
                             start_date=start, end_date=end)
        dataset.satellite = resolve_satellite(dataset, names)  # from the name, or recognised from the bands
        return dataset

    def get_compute_device(self, use_gpu: bool = True) -> ComputeDeviceDTO:
        return self._backend(use_gpu).device

    def list_formulas(self) -> list[FormulaDTO]:
        return self._data_facade.list_formulas()

    def formula_categories(self) -> list[tuple[str, str]]:
        return self._data_facade.formula_categories()

    # ------------------------------------------------------------- helpers
    def _analysis(self, category: str) -> IAnalysis:
        for analysis in self._analyses:
            if analysis.get_category() == category:
                return analysis
        raise AnalysisError(f"There is no {category} analysis.")

    def _backend(self, use_gpu: bool) -> ComputeBackend:
        return self._select(self._find_gpus(), use_gpu)
