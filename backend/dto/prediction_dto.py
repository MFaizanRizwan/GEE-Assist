"""Machine-learning prediction: what the user asks for, and what comes back.

Four tasks, all from a time series of GeoTIFFs of one place (the past ones and the present):

* ``forecast``  – a layer's future values (e.g. NDVI next season), pixel by pixel;
* ``change``    – the future land cover (class) of every pixel, and where it changes;
* ``classify``  – a land-cover map of the present image, learnt from labelled pixels;
* ``anomaly``   – pixels whose present value is unusual for them, given their past.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from backend.dto.analysis_dto import GpuDTO

FORECAST, CHANGE, CLASSIFY, ANOMALY = "forecast", "change", "classify", "anomaly"
TASKS = (FORECAST, CHANGE, CLASSIFY, ANOMALY)

TASK_LABELS = {
    FORECAST: "Forecast future values",
    CHANGE: "Predict future land cover",
    CLASSIFY: "Classify the present image",
    ANOMALY: "Detect anomalies",
}


@dataclass(frozen=True)
class PredictionInputDTO:
    """One GeoTIFF of the series and the date it shows."""

    path: str
    date: str                 # "YYYY-MM-DD"
    label: str = ""           # shown to the user (file or dataset name)


@dataclass(frozen=True)
class RasterBandsDTO:
    """What a GeoTIFF offers the prediction page: its bands and the date its name suggests."""

    path: str
    name: str
    bands: tuple[str, ...]
    date: str = ""            # guessed from the name / metadata ("" when unknown)
    width: int = 0
    height: int = 0
    categorical: tuple[str, ...] = ()   # bands that look like class codes (small whole numbers)


@dataclass(frozen=True)
class AlgorithmDTO:
    """An algorithm the user can pick."""

    key: str
    label: str
    family: str               # e.g. "Linear models", "Tree ensembles", "Deep learning"
    tasks: tuple[str, ...]
    library: str              # "numpy", "scikit-learn", "xgboost", "lightgbm" or "pytorch"
    available: bool
    description: str = ""
    recommended: bool = False
    missing: str = ""         # why it cannot run (a library is not installed)


@dataclass
class PredictionOptionsDTO:
    """Techniques applied around the algorithms."""

    sample_size: int = 20_000        # training pixels drawn from the series
    working_size: int = 512          # longest side of the grid the prediction is computed on
    lags: int = 3                    # past dates used as features (forecast)
    tune: bool = False               # randomised hyperparameter search (slower)
    ensemble: bool = True            # add an ensemble of the best three models
    pca: bool = False                # reduce the features with PCA first (classify)
    cross_validation: bool = False   # k-fold scores instead of one held-out split (classify)
    importance: bool = True          # permutation importance of the best model's features
    contamination: float = 0.05      # share of pixels flagged as anomalies
    neighbourhood: int = 1           # window radius of class shares around a pixel (change)
    use_gpu: bool = True             # train XGBoost / PyTorch models on an NVIDIA GPU when one works
    seed: int = 7


@dataclass(frozen=True)
class PredictionDeviceDTO:
    """Where the Prediction page trains: which libraries run on the GPU, and why (not)."""

    device_name: str                            # e.g. "NVIDIA GeForce RTX 3060" or "CPU"
    gpu_libraries: tuple[str, ...] = ()         # libraries that train on the GPU, e.g. ("xgboost", "pytorch")
    gpus: tuple[GpuDTO, ...] = ()               # every graphics card found
    reason: str = ""                            # what runs where, or how to enable the GPU

    @property
    def uses_gpu(self) -> bool:
        return bool(self.gpu_libraries)

    @property
    def has_nvidia(self) -> bool:
        return any(gpu.vendor == "NVIDIA" and gpu.is_dedicated for gpu in self.gpus)


@dataclass
class PredictionRequestDTO:
    task: str
    inputs: list[PredictionInputDTO]        # in any order; sorted by date, the last is the present
    band: str = ""                          # the value / class band (forecast, anomaly, change)
    target_date: str = ""                   # the date to predict (forecast, change)
    algorithms: list[str] = field(default_factory=list)
    options: PredictionOptionsDTO = field(default_factory=PredictionOptionsDTO)
    # classify: where the training labels come from
    label_path: str = ""                    # a class GeoTIFF, or a shapefile of labelled points/areas
    label_band: str = ""                    # its band (GeoTIFF)
    label_field: str = ""                   # its attribute (shapefile)


@dataclass
class ModelScoreDTO:
    """How one algorithm did on held-out data, and its map."""

    key: str
    label: str
    metrics: dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0
    error: str = ""                          # why it failed ("" when it ran)
    rank: int = 0                            # 1 = best
    importance: list[tuple[str, float]] = field(default_factory=list)
    prediction: Any = None                   # numpy float32 (height, width): values, classes or scores
    confidence: Any = None                   # probability of the predicted class / anomaly score 0-1
    device: str = ""                         # "GPU" when it trained on the GPU ("" = CPU)


@dataclass
class PredictionResultDTO:
    task: str
    band: str
    target_date: str
    present_date: str
    scores: list[ModelScoreDTO]              # ranked, best first; failed ones last
    primary_metric: str                      # what the ranking used, e.g. "RMSE"
    higher_is_better: bool
    width: int
    height: int
    bounds: tuple[float, float, float, float]    # west, south, east, north (EPSG:4326)
    crs: str
    transform: tuple[float, ...]             # affine of the working grid (a, b, c, d, e, f)
    present: Any = None                      # the present layer on the working grid (for comparison)
    uncertainty: Any = None                  # spread between the best models (forecast)
    classes: list[tuple[int, str, str]] = field(default_factory=list)  # (code, name, colour)
    feature_names: list[str] = field(default_factory=list)
    validation: str = ""                     # how the scores were obtained
    notes: list[str] = field(default_factory=list)
    scale: float = 1.0                       # source pixels per working pixel
    device: str = "CPU"                      # where the models trained, e.g. "GPU: NVIDIA GeForce RTX 3060"

    @property
    def best(self) -> ModelScoreDTO | None:
        return next((s for s in self.scores if not s.error), None)


class PredictionProgress:
    """Shared between the page and the worker: how far it is, and whether to stop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.fraction = 0.0
        self.message = "Starting…"
        self._cancelled = False

    def update(self, fraction: float, message: str) -> None:
        with self._lock:
            self.fraction = max(0.0, min(1.0, fraction))
            self.message = message

    def snapshot(self) -> tuple[float, str]:
        with self._lock:
            return self.fraction, self.message

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled
