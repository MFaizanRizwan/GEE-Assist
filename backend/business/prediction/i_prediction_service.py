from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.prediction_dto import (
    AlgorithmDTO,
    PredictionProgress,
    PredictionRequestDTO,
    PredictionResultDTO,
    RasterBandsDTO,
)


class IPredictionService(ABC):
    """«interface» IPredictionService. Machine-learning prediction from past and present GeoTIFFs."""

    @abstractmethod
    def algorithms(self, task: str) -> list[AlgorithmDTO]:
        """The algorithms offered for a task, with whether each can run here."""

    @abstractmethod
    def describe(self, path: str) -> RasterBandsDTO:
        """A GeoTIFF's bands, the date its name suggests and which bands hold class codes."""

    @abstractmethod
    def run(self, request: PredictionRequestDTO, progress: PredictionProgress | None = None) -> PredictionResultDTO:
        """Train, score and rank the chosen algorithms and predict. ``PredictionError`` if it cannot."""

    @abstractmethod
    def save(self, result: PredictionResultDTO, path: str, key: str = "") -> str:
        """Write one model's prediction (the best by default) as a GeoTIFF; returns its path."""
