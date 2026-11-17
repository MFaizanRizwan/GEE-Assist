from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.project_dto import ProjectDTO
from backend.dto.report_dto import ExplanationFileDTO, ReportDTO


class IReportService(ABC):
    """Class diagram: «interface» IReportService (UC-09 Generate Report)."""

    @abstractmethod
    def list_explanations(self, project: ProjectDTO) -> list[ExplanationFileDTO]:
        """The AI explanations saved in the project's explanation folder, newest first."""

    @abstractmethod
    def build_report(self, explanation_path: str, project: ProjectDTO) -> ReportDTO:
        """What goes into the PDF: a picture of each layer of the explained result, then the explanation.

        Raises:
            ReportError: the explanation cannot be read.
        """

    @abstractmethod
    def create_report(self, explanation_path: str, project: ProjectDTO) -> str:
        """Write the explanation's report as a PDF in the project's reports folder (replacing an
        earlier one of the same explanation); returns its path.

        Raises:
            ReportError: the explanation cannot be read, or the PDF cannot be written.
        """

    @abstractmethod
    def report_path(self, explanation_path: str, project: ProjectDTO) -> str:
        """Where the explanation's PDF is kept: ``<project>/reports/<explanation>.pdf``."""

    @abstractmethod
    def export_report(self, pdf_path: str, destination: str) -> str:
        """Copy a report's PDF to ``destination`` (a file the user chose); returns where it went.

        Raises:
            ReportError: the PDF is missing or cannot be copied there.
        """
