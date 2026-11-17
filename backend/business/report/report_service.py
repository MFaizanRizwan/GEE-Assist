"""Class diagram: ReportService. UC-09 Generate Report, from a saved AI explanation.

A report is made from an explanation in ``<project>/explanation/``: first a picture of each
layer of the analysis result it explains (``<project>/analysis/<result>.tif``, coloured as on
the Analysis page), then the explanation exactly as saved (Markdown). The PDF itself is drawn
by the UI (``frontend/report_pdf.py``) and kept here in ``<project>/reports/``, named after
the explanation, from where it can be exported anywhere.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from backend.business.explanation.explanation_service import EXPLANATION_SUFFIX
from backend.business.explanation.previews import describe_legend, rgba_to_png
from backend.business.map.i_map_service import IMapService
from backend.business.report.i_report_service import IReportService
from backend.dto.project_dto import ProjectDTO
from backend.dto.report_dto import ExplanationFileDTO, ReportDTO, ReportImageDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import GeeAssistError, ReportError

logger = logging.getLogger(__name__)

IMAGE_SIZE = 1400                               # longer side of each layer picture in the report
_RESULT_LINE = re.compile(r"^- Result: (?P<name>.+?\.tiff?)\s*$", re.MULTILINE | re.IGNORECASE)
_EXPLAINED_LINE = re.compile(r"^- Explained: (?P<when>\S+)", re.MULTILINE)
_NUMBERED = re.compile(rf"{re.escape(EXPLANATION_SUFFIX.removesuffix('.md'))}(_\d+)?$")


class ReportService(IReportService):
    def __init__(self, map_service: IMapService, image_size: int = IMAGE_SIZE,
                 now: Callable[[], datetime] = datetime.now):
        self._map_service = map_service
        self._image_size = image_size
        self._now = now

    # ------------------------------------------------------------- IReportService
    def list_explanations(self, project: ProjectDTO) -> list[ExplanationFileDTO]:
        folder = Path(project.explanation_dir)
        if not folder.is_dir():
            return []
        files = []
        for path in folder.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                logger.warning("Could not read the explanation %s", path, exc_info=True)
                continue
            report = Path(self.report_path(str(path), project))
            files.append(ExplanationFileDTO(
                path=str(path), title=_title(text, path), result_name=_result_name(text, path),
                explained_at=_explained_at(text, path), report_path=str(report) if report.is_file() else "",
            ))
        return sorted(files, key=lambda item: item.explained_at, reverse=True)

    def build_report(self, explanation_path: str, project: ProjectDTO) -> ReportDTO:
        path = Path(explanation_path)
        try:
            markdown = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReportError(f"The explanation {path.name} cannot be read: {exc.strerror or exc}") from exc
        result = Path(project.analysis_dir) / _result_name(markdown, path)
        images, note = self._pictures(result)
        return ReportDTO(
            title=_title(markdown, path), explanation_path=str(path), markdown=markdown,
            result_path=str(result) if result.is_file() else "", images=images, note=note,
            created_at=self._now().isoformat(timespec="seconds"),
        )

    def report_path(self, explanation_path: str, project: ProjectDTO) -> str:
        return str(Path(project.reports_dir) / (Path(explanation_path).stem + ".pdf"))

    def save_report(self, report: ReportDTO, pdf: bytes, project: ProjectDTO) -> str:
        target = Path(self.report_path(report.explanation_path, project))
        temporary = target.with_name(target.name + ".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(pdf)
            temporary.replace(target)  # a reader never sees half a PDF
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ReportError(f"Could not save the report to {target}: {exc.strerror or exc}. "
                              "Close it if it is open in a PDF viewer and try again.") from exc
        return str(target)

    def export_report(self, pdf_path: str, destination: str) -> str:
        source, target = Path(pdf_path), Path(destination)
        if target.suffix.lower() != ".pdf":
            target = target.with_name(target.name + ".pdf")
        if not source.is_file():
            raise ReportError("The report is no longer there. Create it again.")
        try:
            if target.exists() and source.resolve() == target.resolve():
                return str(target)  # exported onto itself: nothing to do
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        except OSError as exc:
            raise ReportError(f"Could not export the report to {target}: {exc.strerror or exc}") from exc
        return str(target)

    # ------------------------------------------------------------- pictures
    def _pictures(self, tif: Path) -> tuple[tuple[ReportImageDTO, ...], str]:
        """A picture of each layer of the result GeoTIFF; none (and why) if it cannot be drawn."""
        if not tif.is_file():
            return (), f"The analysis result {tif.name} is not in the project's analysis folder, so the report " \
                       "has no picture of it."
        try:
            info = self._map_service.describe(str(tif))
            if info.result_layers:  # an analysis result: each layer in the Analysis page's colours
                result = ResultDTO(id="", category="", output_path=str(tif), layers=list(info.result_layers))
                layers = self._map_service.build_layers(result, self._image_size)
                return tuple(ReportImageDTO(_layer_title(layer.name, layer.legend), rgba_to_png(layer.data),
                                            layer.width, layer.height, describe_legend(layer.legend))
                             for layer in layers), ""
            presets = self._map_service.view_presets(info)
            if not presets:
                return (), f"{tif.name} has no band that can be drawn."
            view = self._map_service.render(info, presets[0], self._image_size)
            return (ReportImageDTO(presets[0].label, rgba_to_png(view.rgba), view.width, view.height,
                                   describe_legend(view.legend)),), ""
        except GeeAssistError as exc:
            logger.warning("Could not draw %s for the report", tif, exc_info=True)
            return (), f"The analysis result could not be drawn: {exc}"


# ----------------------------------------------------------------------------- reading explanations
def _title(markdown: str, path: Path) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _result_name(markdown: str, path: Path) -> str:
    """The result GeoTIFF an explanation is about: its "- Result:" line, else its own file name."""
    match = _RESULT_LINE.search(markdown)
    if match:
        return Path(match.group("name").strip()).name
    return _NUMBERED.sub("", path.stem) + ".tif"  # "<result>_explanation_2.md" -> "<result>.tif"


def _explained_at(markdown: str, path: Path) -> str:
    match = _EXPLAINED_LINE.search(markdown)
    if match:
        return match.group("when")
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def _layer_title(name: str, legend) -> str:
    return getattr(legend, "title", "") or name
