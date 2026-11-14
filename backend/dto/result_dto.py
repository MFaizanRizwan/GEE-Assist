"""Class diagram: ResultDTO (domain model: AnalysisResult). What an analysis produced."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.dto.download_dto import DatasetDTO


@dataclass(frozen=True)
class ResultLayerDTO:
    """One band of the result GeoTIFF: which process made it and how to show it."""

    key: str                                    # band name in the GeoTIFF, e.g. "NDVI", "dNBR", "LST_trend"
    label: str                                  # shown to the user, e.g. "NDVI"
    style: str                                  # colour style, see backend/business/map/layer_styles.py
    unit: str = ""                              # e.g. "°C", "km²"
    low: float | None = None                    # fixed display range; None = stretched to the data
    high: float | None = None
    classes: str = ""                           # class table for "classes"/"transition" styles: "dynamic_world" or "modis_igbp"


@dataclass
class ResultDTO:
    """The processes that ran, their numbers (``metrics``) and the GeoTIFF they wrote."""

    id: str
    category: str
    processes: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)  # e.g. {"NDVI mean": 0.42, "Water area (km²)": 3.1}
    output_path: str = ""                       # GeoTIFF: one band per layer, no-data = -9999
    created_at: str = ""                        # ISO timestamp
    dataset: DatasetDTO | None = None
    layers: list[ResultLayerDTO] = field(default_factory=list)
    device: str = ""                            # where it ran, e.g. "GPU: NVIDIA GeForce RTX 3060" or "CPU"
    seconds: float = 0.0                        # how long it took
    notes: list[str] = field(default_factory=list)
    saved: bool = False                         # False: a temporary file, deleted unless the user saves it
