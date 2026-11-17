from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO
from backend.dto.result_dto import ResultDTO


class IExplanationService(ABC):
    """Class diagram: «interface» IExplanationService (UC-08 Get AI Explanation)."""

    @abstractmethod
    def prepare(self, result: ResultDTO) -> ExplanationRequestDTO:
        """What Gemini is given about a saved result: the analysis, its settings, the metadata
        before and after it, its numbers and a preview of each layer.

        Raises:
            ExplanationError: the result is not saved, or its GeoTIFF is missing.
        """

    @abstractmethod
    def explain(self, request: ExplanationRequestDTO, folder: str) -> ExplanationDTO:
        """Send the request (with the saved GeoTIFF) to Gemini and keep its answer in ``folder``
        (the project's explanation folder) as ``<result>_explanation.md``.

        Raises:
            ExplanationError: the GeoTIFF is no longer there.
            LLMServiceError: Gemini is not set up or failed.
        """
