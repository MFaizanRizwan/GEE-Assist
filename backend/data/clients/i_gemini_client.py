from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto import FormDTO
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO


class IGeminiClient(ABC):
    """Class diagram: IGeminiClient. Gateway to the Gemini LLM."""

    @abstractmethod
    def set_api_key(self, api_key: str) -> None:
        """Use another Gemini API key from now on."""

    @abstractmethod
    def process_query(self, prompt: str) -> FormDTO:
        """Interpret Query (LLM): turn a natural-language request into a FormDTO.

        The result is Gemini's raw interpretation; RequestService checks it
        against the supported datasets before it reaches the form.

        Raises:
            LLMServiceError: not configured, the API failed, or the answer is unusable.
        """

    @abstractmethod
    def generate_explanation(self, request: ExplanationRequestDTO) -> ExplanationDTO:
        """UC-08 Get AI Explanation: explain an analysis result.

        Gemini is given the prompt (the analysis, the metadata before and after it, its
        numbers), the saved result GeoTIFF and a PNG preview of each layer.

        Raises:
            LLMServiceError: not configured, the API failed, or the GeoTIFF is missing.
        """
