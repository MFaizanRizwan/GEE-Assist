"""What every analysis category shares: formulas -> layers, availability checks, running.

A concrete analysis (``WaterAnalysis``, ``VegetationAnalysis``, ...) only names its
category; processes that are plain formulas (``index_math.INDEX_FUNCTIONS``) work with
no more code. Processes that are more than a formula (water masks, LST trends, land-
cover transitions, PCA) override ``_special_check`` and ``_special_layers``.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.business.analysis.compute_device import ComputeBackend, cpu_backend
from backend.business.analysis.i_analysis import IAnalysis
from backend.business.analysis.index_math import INDEX_FUNCTIONS, IndexDef, nd
from backend.business.analysis.raster_engine import (
    Accumulator,
    LayerSpec,
    MinMaxPass,
    Period,
    RasterEngine,
    ScenePass,
)
from backend.business.analysis.sensors import PRODUCT_BANDS, resolve_satellite
from backend.business.download.naming import parse_dataset_name
from backend.business.map.band_roles import ALL_ROLES, band_roles
from backend.config import DEFAULT_ANALYSIS_DIR
from backend.dto.analysis_dto import AnalysisConfigDTO, FormulaDTO, ProcessOptionDTO
from backend.dto.download_dto import DatasetDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import AnalysisError

ROLE_NAMES = {"nir": "NIR", "swir1": "SWIR1", "swir2": "SWIR2", "re1": "red-edge 1", "re2": "red-edge 2",
              "re3": "red-edge 3", "nir2": "narrow NIR", "thermal": "thermal", "vv": "VV", "vh": "VH",
              "hh": "HH", "hv": "HV"}


def role_name(role: str) -> str:
    return ROLE_NAMES.get(role, role)


def read_band_names(path: str) -> tuple[str, ...]:
    """Band names of a GeoTIFF (its band descriptions)."""
    import rasterio

    try:
        with rasterio.open(path) as src:
            return tuple(name or f"Band {index}" for index, name in enumerate(src.descriptions, start=1))
    except rasterio.errors.RasterioIOError as exc:
        raise AnalysisError(f"Cannot open {Path(path).name}: it is missing or not a GeoTIFF.") from exc


def make_period(dataset: DatasetDTO) -> Period:
    names = read_band_names(dataset.path)
    satellite = resolve_satellite(dataset, names)
    date = dataset.start_date or parse_dataset_name(Path(dataset.path).stem)[1]
    return Period(dataset, satellite, names, band_roles(satellite, names, ALL_ROLES), date)


def _is_out_of_memory(exc: BaseException) -> bool:
    return "OutOfMemory" in type(exc).__name__ or "out of memory" in str(exc).lower()


class BaseAnalysis(IAnalysis):
    CATEGORY = ""

    def __init__(self) -> None:
        self.config = AnalysisConfigDTO(self.CATEGORY)       # class diagram: -config
        self.available_processes: list[str] = []              # class diagram: -availableProcesses
        self._formulas: dict[str, FormulaDTO] = {}

    # ------------------------------------------------------------- IAnalysis
    def configure(self, config: AnalysisConfigDTO) -> None:
        self.config = config
        self._formulas = {formula.key: formula for formula in config.formulas}
        self.available_processes = [formula.key for formula in config.formulas]

    def get_category(self) -> str:
        return self.CATEGORY

    def list_available(self, dataset: DatasetDTO) -> list[str]:
        return [option.key for option in self.process_options(dataset) if option.available]

    def process_options(self, dataset: DatasetDTO) -> list[ProcessOptionDTO]:
        period = make_period(dataset)
        options = []
        for key in self.available_processes:
            formula = self._formulas[key]
            reason = self._why_not(formula, period)
            options.append(ProcessOptionDTO(key, formula.name, reason is None, reason or "", formula.periods,
                                            formula.params))
        return options

    def run(self, processes: list[str], dataset: DatasetDTO, params: dict[str, Any]) -> ResultDTO:
        if not processes:
            raise AnalysisError("Choose at least one process to run.")
        unknown = [key for key in processes if key not in self._formulas]
        if unknown:
            raise AnalysisError(f"{self.CATEGORY} analysis has no process {', '.join(unknown)}.")
        backend: ComputeBackend = params.get("_backend") or cpu_backend()
        compare = list(params.get("_compare_with") or [])
        primary = make_period(dataset)
        periods = [primary] + [make_period(other) for other in compare]
        for key in processes:
            formula = self._formulas[key]
            reason = self._why_not(formula, primary)
            if reason:
                raise AnalysisError(f"{key}: {reason}")
            if len(periods) < formula.periods:
                raise AnalysisError(f"{key} compares {formula.periods} datasets of the same place: choose an "
                                    "earlier dataset to compare with.")
            for other in periods[1:]:
                other_reason = self._why_not(formula, other) if formula.periods > 1 else None
                if other_reason:
                    raise AnalysisError(f"{key}: {Path(other.dataset.path).stem}: {other_reason}")
        user_params = {k: v for k, v in params.items() if not k.startswith("_")}
        output = params.get("_output_path") or str(self.default_output(dataset))
        notes: list[str] = []
        started = time.perf_counter()
        try:
            metrics, layers = self._run_on(backend, periods, processes, user_params, output, params, notes)
        except Exception as exc:
            if not (backend.uses_gpu and _is_out_of_memory(exc)):
                raise
            backend.free()
            notes.append("The GPU ran out of memory, so this analysis ran on the CPU.")
            backend = cpu_backend(backend.device.gpus, backend.device.reason)
            metrics, layers = self._run_on(backend, periods, processes, user_params, output, params, notes)
        result = ResultDTO(
            id=uuid.uuid4().hex[:12], category=self.CATEGORY, processes=list(processes), metrics=metrics,
            output_path=output, created_at=datetime.now().isoformat(timespec="seconds"), dataset=dataset,
            layers=[layer.to_dto() for layer in layers], device=backend.label(),
            seconds=round(time.perf_counter() - started, 3), notes=notes,
        )
        self._write_summary(result, user_params, compare)
        return result

    # ------------------------------------------------------------- running
    def _run_on(self, backend, periods, processes, user_params, output, params, notes):
        layers: list[LayerSpec] = []
        passes: list[ScenePass] = []
        accumulators: list[Accumulator] = []
        seen: set[str] = set()
        for key in processes:
            new_layers, new_passes, new_accumulators = self._build(key, periods, user_params, notes)
            for layer in new_layers:
                if layer.key not in seen:
                    seen.add(layer.key)
                    layers.append(layer)
            passes += [p for p in new_passes if p.name not in {q.name for q in passes}]
            known = {_identity(a) for a in accumulators}
            accumulators += [a for a in new_accumulators if _identity(a) not in known]
        with RasterEngine(periods, backend, self.config.block_rows) as engine:
            metrics = engine.run(layers, output, user_params, passes, accumulators, params.get("_on_progress"))
        return metrics, layers

    def _build(self, key: str, periods: list[Period], params: dict, notes: list[str]):
        special = self._special_layers(key, periods, params, notes)
        if special is not None:
            return special
        formula = self._formulas[key]
        product = self._product_band(key, periods[-1])
        if product is not None and not self._has_roles(formula, periods[-1]):
            definition = INDEX_FUNCTIONS[key]
            layer = LayerSpec(key, key, lambda block, band=product: block.band(band), definition.style,
                              definition.unit, definition.low, definition.high)
            return [layer], [], []
        definition = INDEX_FUNCTIONS[key]
        if formula.note and not formula.computable:
            raise AnalysisError(formula.note)
        layer = LayerSpec(key, key, self._index_compute(definition), definition.style, definition.unit,
                          definition.low, definition.high)
        return [layer], [scene_pass(name) for name in definition.scene], []

    @staticmethod
    def _index_compute(definition: IndexDef):
        def compute(block):
            params = dict(block.params)
            if len(block.engine.periods) > 1:
                params["before"] = block.before()
            return definition.fn(block.xp, block.roles(), params)

        return compute

    # ------------------------------------------------------------- availability
    def _why_not(self, formula: FormulaDTO, period: Period) -> str | None:
        """Why ``period``'s dataset cannot run ``formula``, or None when it can."""
        if not formula.computable:
            return formula.note or "Reference only: GEE-Assist cannot compute it."
        special = self._special_check(formula, period)
        if special != "":
            return special
        if formula.key not in INDEX_FUNCTIONS:
            return "Not available for this dataset."
        if self._product_band(formula.key, period) is not None:
            return None
        if not period.roles:
            return "GEE-Assist does not recognise this dataset's bands (unknown satellite)."
        missing = [role for role in INDEX_FUNCTIONS[formula.key].roles if role not in period.roles]
        if missing:
            plural = "s" if len(missing) > 1 else ""
            return f"Needs the {_and(role_name(role) for role in missing)} band{plural}, which this dataset does not have."
        return None

    def _special_check(self, formula: FormulaDTO, period: Period) -> str | None:
        """For processes that are more than a formula: None = available, a reason, or "" = not special."""
        return ""

    def _special_layers(self, key: str, periods: list[Period], params: dict, notes: list[str]):
        """(layers, scene passes, accumulators) for a process that is more than a formula, or None."""
        return None

    @staticmethod
    def _has_roles(formula: FormulaDTO, period: Period) -> bool:
        definition = INDEX_FUNCTIONS.get(formula.key)
        return definition is not None and all(role in period.roles for role in definition.roles)

    @staticmethod
    def _product_band(key: str, period: Period) -> str | None:
        band = PRODUCT_BANDS.get(period.satellite, {}).get(key)
        return band if band in period.band_names else None

    # ------------------------------------------------------------- output
    def default_output(self, dataset: DatasetDTO) -> Path:
        name = dataset.name or Path(dataset.path).stem
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_category = "".join(c if c.isalnum() else "-" for c in self.CATEGORY).strip("-")
        return DEFAULT_ANALYSIS_DIR / f"{name}_{safe_category}_{stamp}.tif"

    @staticmethod
    def _write_summary(result: ResultDTO, params: dict, compare: list[DatasetDTO]) -> None:
        """The metrics and settings next to the GeoTIFF, so a result can be reproduced."""
        summary = {
            "id": result.id, "category": result.category, "processes": result.processes,
            "created_at": result.created_at, "device": result.device, "seconds": result.seconds,
            "dataset": result.dataset.path if result.dataset else "",
            "compared_with": [other.path for other in compare],
            "params": {k: v for k, v in params.items() if isinstance(v, (int, float, str, bool))},
            "metrics": result.metrics, "layers": [layer.key for layer in result.layers], "notes": result.notes,
        }
        try:
            Path(result.output_path).with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except OSError:
            pass  # the GeoTIFF is what matters


def scene_pass(name: str) -> ScenePass:
    if name == "NDVI":
        return MinMaxPass("NDVI", lambda block: nd(block.roles()["nir"], block.roles()["red"]))
    if name == "thermal":
        return MinMaxPass("thermal", lambda block: block.roles()["thermal"])
    raise ValueError(name)


def _identity(accumulator: Accumulator) -> tuple:
    """Two accumulators of the same kind over the same layer would add the same numbers twice."""
    return type(accumulator).__name__, getattr(accumulator, "dedupe_key", id(accumulator))


def _and(words) -> str:
    words = list(words)
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
