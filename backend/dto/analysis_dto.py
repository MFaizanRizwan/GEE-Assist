"""DTOs for running analyses on downloaded datasets (UC-06 Run Local Analysis).

Names follow the SRS class diagram: AnalysisConfigDTO (``IAnalysis.configure``),
AnalysisOptionDTO (``getAvailableAnalyses``) and AnalysisRequestDTO (``runAnalysis``).
``FormulaDTO`` is one row of the index reference table (``IFormulaDAO``); the GPU DTOs
describe the computer's graphics cards and the device analyses run on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.dto.download_dto import DatasetDTO


# ----------------------------------------------------------------------------- formulas
@dataclass(frozen=True)
class FormulaDTO:
    """One spectral index, product or method: what it is, how it is computed, what it is for."""

    key: str                                    # e.g. "NDVI", "WaterBodyDetection"
    name: str                                   # e.g. "Normalized Difference Vegetation Index"
    category: str                               # sub-type, e.g. "Burn & fire" (see SUBTYPES in the formula catalogue)
    formula: str                                # shown to the user, e.g. "(NIR − Red) / (NIR + Red)"
    analysis: str = ""                          # its major analysis: "Water", "Vegetation", "LST" or "LULC"
    bands: tuple[str, ...] = ()                 # band roles it needs: "nir", "red", ... (see band_roles.ALL_ROLES)
    use_cases: tuple[str, ...] = ()
    description: str = ""                       # what the value means
    value_range: str = ""                       # e.g. "−1 to 1"
    interpretation: str = ""                    # how to read the values
    reference: str = ""                         # who published it
    computable: bool = True                     # False: shown in the table, but GEE-Assist cannot compute it locally
    note: str = ""                              # e.g. why it is not computable, or that it is an approximation
    periods: int = 1                            # datasets it needs: 2 = before and after (e.g. dNBR)
    params: tuple[str, ...] = ()                # parameter names it reads, e.g. ("savi_l",)
    aliases: tuple[str, ...] = ()               # other names, e.g. ("GCI",)


# ----------------------------------------------------------------------------- analysis
@dataclass(frozen=True)
class AnalysisConfigDTO:
    """What an analysis needs before it runs: its formulas and the device to compute on."""

    category: str
    formulas: tuple[FormulaDTO, ...] = ()
    use_gpu: bool = True                        # use a dedicated GPU when there is one that works
    block_rows: int = 1024                      # rows read and computed at a time


@dataclass(frozen=True)
class ProcessOptionDTO:
    """One process of an analysis for one dataset: whether it can run, and if not, why."""

    key: str
    label: str
    available: bool
    reason: str = ""                            # why it is not available, e.g. "needs a SWIR2 band"
    periods: int = 1                            # datasets it needs (2 = an earlier one to compare with)
    params: tuple[str, ...] = ()
    group: str = ""                             # its sub-type, e.g. "Burn & fire"


@dataclass(frozen=True)
class AnalysisOptionDTO:
    """Class diagram: AnalysisOptionDTO. One of the four analyses and its processes for a dataset."""

    category: str                               # "Water", "Vegetation", "LST" or "LULC"
    description: str
    processes: tuple[ProcessOptionDTO, ...] = ()
    label: str = ""                             # e.g. "Land Use / Land Cover"
    subtypes: tuple[str, ...] = ()              # its sub-types in display order, e.g. ("Vegetation indices", ...)

    @property
    def available(self) -> bool:
        return any(process.available for process in self.processes)


@dataclass
class AnalysisRequestDTO:
    """Class diagram: AnalysisRequestDTO. Which processes to run, with which parameters.

    ``compare_with`` holds the other time periods: the earlier dataset for change
    analyses (dNBR, LULC change), every other period for temporal analyses (LST trend).
    """

    category: str
    processes: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    compare_with: list[DatasetDTO] = field(default_factory=list)
    use_gpu: bool = True
    output_dir: str = ""                        # "" = the default analyses folder


# ----------------------------------------------------------------------------- GPUs
GPU_DEDICATED = "dedicated"
GPU_INTEGRATED = "integrated"
GPU_VIRTUAL = "virtual"                         # e.g. Microsoft Basic Display Adapter, remote desktop


@dataclass(frozen=True)
class GpuDTO:
    """A graphics card found on this computer."""

    name: str
    vendor: str                                 # "NVIDIA", "AMD", "Intel", "Microsoft", ...
    kind: str                                   # GPU_DEDICATED, GPU_INTEGRATED or GPU_VIRTUAL
    memory_bytes: int = 0                       # 0 = unknown

    @property
    def is_dedicated(self) -> bool:
        return self.kind == GPU_DEDICATED


@dataclass(frozen=True)
class ComputeDeviceDTO:
    """Where analyses run: the GPU (through CuPy) or the CPU (NumPy), and why."""

    backend: str                                # "cupy" or "numpy"
    device_name: str                            # e.g. "NVIDIA GeForce RTX 3060" or "CPU"
    gpus: tuple[GpuDTO, ...] = ()               # every graphics card found
    reason: str = ""                            # e.g. "No dedicated GPU found." or how to enable the GPU

    @property
    def uses_gpu(self) -> bool:
        return self.backend == "cupy"

    @property
    def dedicated_gpus(self) -> tuple[GpuDTO, ...]:
        return tuple(gpu for gpu in self.gpus if gpu.is_dedicated)
