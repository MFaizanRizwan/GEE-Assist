"""DTOs for PDF reports made from saved AI explanations (UC-09 Generate Report).

A report is made from an AI explanation kept in the project's ``explanation`` folder:
first a picture of each layer of the analysis result (the ``.tif`` it explains), then the
explanation itself (Markdown). The PDF is kept in the project's ``reports`` folder and
can be exported anywhere on the computer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExplanationFileDTO:
    """An AI explanation saved in the project, from which a report can be made."""

    path: str                                   # the .md in <project>/explanation/
    title: str                                  # its first heading, e.g. "AI explanation: Vegetation (NDVI)"
    result_name: str = ""                       # the result GeoTIFF it explains, e.g. "..._NDVI_....tif"
    explained_at: str = ""                      # when it was made (ISO), from the file
    report_path: str = ""                       # its PDF in <project>/reports/, "" if none was made yet

    @property
    def name(self) -> str:
        """The file name, e.g. "result_explanation.md"."""
        return self.path.replace("\\", "/").rsplit("/", 1)[-1]


@dataclass(frozen=True)
class ReportImageDTO:
    """A picture of one layer of the analysis result, as PNG."""

    title: str                                  # e.g. "NDVI"
    png: bytes
    width: int
    height: int
    legend: str = ""                            # how it is coloured, in words


@dataclass(frozen=True)
class ReportDTO:
    """What goes into the PDF: the analysis pictures on top, then the explanation."""

    title: str                                  # the explanation's first heading
    explanation_path: str
    markdown: str                               # the explanation, exactly as saved
    result_path: str = ""                       # the analysis GeoTIFF pictured ("" if not found)
    images: tuple[ReportImageDTO, ...] = ()
    note: str = ""                              # e.g. why there is no picture
    created_at: str = ""                        # ISO timestamp
