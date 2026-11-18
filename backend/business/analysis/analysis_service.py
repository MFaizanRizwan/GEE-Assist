"""Class diagram: AnalysisService (-dataFacade: IDataFacade, -analyses: list[IAnalysis]).

There are four analyses, as in the class diagram (water, vegetation, LST, LULC); each
is configured with its formulas from the formula DAO (through the data facade), which
are grouped into sub-types (e.g. vegetation: indices, moisture & drought, burn & fire). Before every run the compute device is chosen: a dedicated NVIDIA
GPU through CuPy when there is one that works, otherwise the CPU.

Results are written to a temporary folder and kept only when the user saves them
(``save_result``, to a file they choose); the folder is deleted when the app exits.
"""

from __future__ import annotations

import logging

import atexit
import json
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from backend.business.analysis.base_analysis import read_band_names
from backend.business.analysis.compute_device import ComputeBackend, cached_gpus, select_backend
from backend.business.analysis.i_analysis import IAnalysis
from backend.business.analysis.i_analysis_service import IAnalysisService
from backend.business.analysis.lst_analysis import LSTAnalysis
from backend.business.analysis.lulc_analysis import LULCAnalysis
from backend.business.analysis.sensors import resolve_satellite
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
from backend.dto.result_dto import ResultDTO, ResultLayerDTO
from backend.exceptions import AnalysisError


logger = logging.getLogger(__name__)

def default_analyses() -> list[IAnalysis]:
    return [WaterAnalysis(), VegetationAnalysis(), LSTAnalysis(), LULCAnalysis()]


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
        self._scratch: Optional[Path] = None  # temporary folder for results not saved yet
        self._select = select
        self._groups = {major: (label, description, subtypes)
                        for major, label, description, subtypes in data_facade.analysis_groups()}
        formulas = data_facade.list_formulas()
        self._analyses: list[IAnalysis] = analyses if analyses is not None else default_analyses()
        for analysis in self._analyses:
            category = analysis.get_category()
            mine = tuple(formula for formula in formulas if formula.analysis == category)
            analysis.configure(AnalysisConfigDTO(category, mine, block_rows=block_rows))
        order = {category: index for index, category in enumerate(self._groups)}
        self._analyses.sort(key=lambda analysis: order.get(analysis.get_category(), len(order)))

    # ------------------------------------------------------------- IAnalysisService
    def get_available_analyses(self, dataset: DatasetDTO) -> list[AnalysisOptionDTO]:
        options = []
        for analysis in self._analyses:
            category = analysis.get_category()
            label, description, subtypes = self._groups.get(category, (category, "", ()))
            options.append(AnalysisOptionDTO(category, description, tuple(analysis.process_options(dataset)),
                                             label, subtypes))
        return options

    def run_analysis(self, dataset: DatasetDTO, request: AnalysisRequestDTO,
                     on_progress: Optional[Callable[[float], None]] = None) -> ResultDTO:
        analysis = self._analysis(request.category)
        backend = self._backend(request.use_gpu)
        params: dict[str, Any] = dict(request.params)
        params.update(_compare_with=list(request.compare_with), _backend=backend, _on_progress=on_progress)
        folder = Path(request.output_dir) if request.output_dir else self._scratch_folder()
        name = (analysis.default_output(dataset, request.processes).name if hasattr(analysis, "default_output")
                else "result.tif")
        params["_output_path"] = str(folder / name)
        result = analysis.run(list(request.processes), dataset, params)
        result.saved = bool(request.output_dir)  # an explicit folder is the user's choice
        return result

    # ------------------------------------------------------------- saving
    def save_result(self, result: ResultDTO, path: str) -> ResultDTO:
        source, target = Path(result.output_path), Path(path)
        if target.suffix.lower() not in (".tif", ".tiff"):
            target = target.with_suffix(".tif")
        if not source.is_file():
            raise AnalysisError("The result is no longer there: run the analysis again to save it.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                shutil.copyfile(source, target)
                summary = source.with_suffix(".json")
                if summary.is_file():
                    shutil.copyfile(summary, target.with_suffix(".json"))
        except OSError as exc:
            raise AnalysisError(f"Could not save to {target}: {exc.strerror or exc}") from exc
        self.discard_result(result)  # the temporary copy is not needed any more
        return replace(result, output_path=str(target), saved=True)

    def discard_result(self, result: ResultDTO) -> None:
        """Delete an unsaved result's files; saved results and files outside the temporary folder stay."""
        if result.saved or self._scratch is None:
            return
        path = Path(result.output_path)
        if self._scratch not in path.parents:
            return
        for file in (path, path.with_suffix(".json")):
            try:
                file.unlink(missing_ok=True)
            except OSError:
                # Still open (e.g. the map layers are being drawn from it, or a virus scanner reads it):
                # leave it; the whole temporary folder is deleted when the app closes.
                logger.info("Could not delete the temporary result %s yet; it goes when the app closes", file)

    def cleanup(self) -> None:
        """Delete every unsaved result (called when the app exits)."""
        if self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)
            self._scratch = None

    def _scratch_folder(self) -> Path:
        if self._scratch is None or not self._scratch.is_dir():
            self._scratch = Path(tempfile.mkdtemp(prefix="gee-assist-analysis-"))
            atexit.register(self.cleanup)
        return self._scratch

    def list_saved_results(self, folder: str) -> list[ResultDTO]:
        """The analysis results saved in ``folder`` (GeoTIFFs), newest first."""
        directory = Path(folder)
        if not directory.is_dir():
            return []
        files = [path for path in directory.iterdir() if path.suffix.lower() in (".tif", ".tiff") and path.is_file()]
        results = [self.load_result(str(path)) for path in files]
        return sorted(results, key=lambda result: result.created_at, reverse=True)

    def load_result(self, path: str) -> ResultDTO:
        """A saved result GeoTIFF as a ResultDTO, from the settings and numbers saved next to it (.json).

        A GeoTIFF without its .json is still listed, with only what its file tells (its name, when it was made).
        """
        file = Path(path)
        summary = _read_summary(file)
        created = str(summary.get("created_at") or "") or _modified_at(file)
        dataset_path = str(summary.get("dataset") or "")
        layers = []
        for item in summary.get("styles") or []:
            try:
                layers.append(ResultLayerDTO(**{key: item[key] for key in ResultLayerDTO.__dataclass_fields__
                                                if key in item}))
            except (TypeError, KeyError):
                continue
        return ResultDTO(
            id=str(summary.get("id") or file.stem), category=str(summary.get("category") or ""),
            processes=[str(p) for p in summary.get("processes") or []],
            metrics={str(k): v for k, v in (summary.get("metrics") or {}).items() if isinstance(v, (int, float))},
            output_path=str(file), created_at=created,
            dataset=self._dataset_of(dataset_path) if dataset_path else None, layers=layers,
            device=str(summary.get("device") or ""), seconds=float(summary.get("seconds") or 0.0),
            notes=[str(n) for n in summary.get("notes") or []], saved=True,
        )

    def _dataset_of(self, path: str) -> DatasetDTO:
        """The dataset a result was made from: read from its file, or only its name when it is gone."""
        if Path(path).is_file():
            try:
                return self.describe_dataset(path)
            except (OSError, AnalysisError, ValueError):
                logger.info("Could not read the dataset %s of a saved result", path, exc_info=True)
        satellite, start, end = parse_dataset_name(Path(path).stem)
        return DatasetDTO(id="", source="", path=path, name=Path(path).stem, satellite=satellite,
                          start_date=start, end_date=end)

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

    def analysis_groups(self) -> list[tuple[str, str, str, tuple[str, ...]]]:
        return self._data_facade.analysis_groups()

    # ------------------------------------------------------------- helpers
    def _analysis(self, category: str) -> IAnalysis:
        for analysis in self._analyses:
            if analysis.get_category() == category:
                return analysis
        raise AnalysisError(f"There is no {category} analysis.")

    def _backend(self, use_gpu: bool) -> ComputeBackend:
        return self._select(self._find_gpus(), use_gpu)


def _read_summary(tif: Path) -> dict[str, Any]:
    """The .json saved next to a result GeoTIFF (its settings, numbers and layer styles); {} if none."""
    try:
        data = json.loads(tif.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _modified_at(file: Path) -> str:
    try:
        return datetime.fromtimestamp(file.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""
