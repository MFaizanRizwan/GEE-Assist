"""Class diagram: ExplanationService (-dataFacade: IDataFacade). UC-08 Get AI Explanation.

An explanation is made from a *saved* analysis result: its GeoTIFF is in the open
project's analysis folder before anything is sent to Gemini. The service gathers what
Gemini is given:

* which analysis ran: its label, processes (from the formula table) and parameters;
* the metadata **before** the analysis: the dataset analysed, and any earlier dataset
  it was compared with (satellite, dates, bands, size, pixel size, area, ...);
* the metadata **after** the analysis: the result GeoTIFF, its layers and numbers;
* the result GeoTIFF itself and a PNG preview of each layer.

Gemini's answer is kept next to the result as ``<result>_explanation.md``.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.business.explanation.i_explanation_service import IExplanationService
from backend.business.explanation.previews import describe_legend, rgba_to_png
from backend.business.map.i_map_service import IMapService
from backend.data.i_data_facade import IDataFacade
from backend.dto.download_dto import DatasetDTO
from backend.dto.explanation_dto import (
    ExplanationDTO,
    ExplanationRequestDTO,
    LayerInfoDTO,
    ProcessInfoDTO,
    RasterMetadataDTO,
)
from backend.dto.result_dto import ResultDTO
from backend.exceptions import ExplanationError, GeeAssistError

logger = logging.getLogger(__name__)

PREVIEW_SIZE = 768                              # longer side of each layer preview sent to Gemini
EXPLANATION_SUFFIX = "_explanation.md"
KM_PER_DEGREE_LAT = 110.574
KM_PER_DEGREE_LON = 111.320                     # at the equator; times cos(latitude) elsewhere


class ExplanationService(IExplanationService):
    def __init__(self, data_facade: IDataFacade, map_service: IMapService, preview_size: int = PREVIEW_SIZE,
                 now: Callable[[], datetime] = datetime.now):
        self._data_facade = data_facade
        self._map_service = map_service
        self._preview_size = preview_size
        self._now = now

    # ------------------------------------------------------------- IExplanationService
    def prepare(self, result: ResultDTO) -> ExplanationRequestDTO:
        if not result.saved:
            raise ExplanationError("Save the result in the project first: its GeoTIFF is what Gemini is sent.")
        if not Path(result.output_path).is_file():
            raise ExplanationError(f"The result {Path(result.output_path).name} is no longer there. "
                                   "Run the analysis again.")
        summary = _read_summary(result.output_path)
        layers, previews = self._layers(result)
        return ExplanationRequestDTO(
            result=result,
            category=result.category,
            category_label=self._category_label(result.category),
            processes=tuple(self._process(key) for key in result.processes),
            params=dict(summary.get("params") or {}),
            before=self.metadata(result.dataset.path, result.dataset) if result.dataset else None,
            compared_with=tuple(self.metadata(path) for path in summary.get("compared_with") or () if path),
            after=self.metadata(result.output_path),
            layers=layers,
            previews=previews,
        )

    def explain(self, request: ExplanationRequestDTO) -> ExplanationDTO:
        if not Path(request.tif_path).is_file():
            raise ExplanationError(f"The result {Path(request.tif_path).name} is no longer there. "
                                   "Run the analysis again.")
        explanation = self._data_facade.generate_explanation(request)
        explanation = replace(explanation, request=request, created_at=self._now().isoformat(timespec="seconds"))
        return replace(explanation, saved_path=self._keep(explanation))

    # ------------------------------------------------------------- metadata
    def metadata(self, path: str, dataset: DatasetDTO | None = None) -> RasterMetadataDTO:
        """What the GeoTIFF at ``path`` holds and covers; only the dataset's own details if it cannot be read."""
        try:
            info = self._map_service.describe(path)
        except GeeAssistError:
            logger.info("Could not read %s for its metadata", path, exc_info=True)
            dataset = dataset or DatasetDTO(id="", source="", path=path)
            return RasterMetadataDTO(
                name=dataset.name or Path(path).stem, path=path, satellite=dataset.satellite or "",
                start_date=dataset.start_date or "", end_date=dataset.end_date or "",
                bands=tuple(dataset.bands), size_bytes=dataset.size_bytes or 0,
            )
        pixel_size, area = ground_size(info.bounds, info.width, info.height)
        return RasterMetadataDTO(
            name=info.name, path=info.path,
            satellite=info.satellite or (dataset.satellite if dataset else "") or "",
            start_date=info.start_date or (dataset.start_date if dataset else "") or "",
            end_date=info.end_date or (dataset.end_date if dataset else "") or "",
            bands=tuple(info.band_names), width=info.width, height=info.height, crs=info.crs,
            bounds=tuple(info.bounds), pixel_size_m=pixel_size, area_km2=area, dtype=info.dtype,
            nodata=info.nodata, size_bytes=info.size_bytes,
        )

    def _process(self, key: str) -> ProcessInfoDTO:
        try:
            formula = self._data_facade.get_formula(key)
        except GeeAssistError:
            formula = None
        if formula is None:
            return ProcessInfoDTO(key)
        return ProcessInfoDTO(key, formula.name, formula.formula, formula.value_range,
                              formula.interpretation or formula.description)

    def _category_label(self, category: str) -> str:
        try:
            groups = self._data_facade.analysis_groups()
        except GeeAssistError:
            return category
        return next((label for major, label, *_ in groups if major == category), category)

    def _layers(self, result: ResultDTO) -> tuple[tuple[LayerInfoDTO, ...], tuple[bytes, ...]]:
        """Each result layer, and a PNG of it coloured as on the Analysis page (none if it cannot be drawn)."""
        try:
            drawn = {layer.id: layer for layer in self._map_service.build_layers(result, self._preview_size)}
        except GeeAssistError:
            logger.warning("Could not draw the layers of %s for Gemini", result.output_path, exc_info=True)
            drawn = {}
        layers, previews = [], []
        for layer in result.layers:
            picture = drawn.get(layer.key)
            layers.append(LayerInfoDTO(layer.key, layer.label, layer.unit,
                                       describe_legend(picture.legend) if picture else ""))
            if picture is not None:
                previews.append(rgba_to_png(picture.data))
        # Previews are sent in layer order: keep the drawn layers first so the two lists line up.
        layers.sort(key=lambda layer: layer.key not in drawn)
        return tuple(layers), tuple(previews)

    # ------------------------------------------------------------- keeping the answer
    def _keep(self, explanation: ExplanationDTO) -> str:
        """Write the explanation next to the result GeoTIFF; "" if that is not possible."""
        request = explanation.request
        target = Path(request.tif_path).with_name(Path(request.tif_path).stem + EXPLANATION_SUFFIX)
        try:
            target.write_text(explanation_markdown(explanation), encoding="utf-8")
        except OSError:
            logger.warning("Could not save the explanation to %s", target, exc_info=True)
            return ""
        return str(target)


# ----------------------------------------------------------------------------- helpers
def ground_size(bounds, width: int, height: int) -> tuple[float | None, float | None]:
    """(pixel size in metres, area in km²) of a raster with ``bounds`` in degrees, approximately."""
    if not bounds or width <= 0 or height <= 0:
        return None, None
    west, south, east, north = bounds
    if not all(math.isfinite(v) for v in bounds) or east <= west or north <= south:
        return None, None
    width_km = (east - west) * KM_PER_DEGREE_LON * math.cos(math.radians((south + north) / 2))
    height_km = (north - south) * KM_PER_DEGREE_LAT
    pixel_m = math.sqrt((width_km / width) * (height_km / height)) * 1000
    return pixel_m, width_km * height_km


def _read_summary(tif_path: str) -> dict[str, Any]:
    """The settings saved next to the result (``<result>.json``): its parameters and compared datasets."""
    try:
        data = json.loads(Path(tif_path).with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def explanation_markdown(explanation: ExplanationDTO) -> str:
    """The explanation as kept in the project: what was explained, the metadata, then Gemini's answer."""
    request = explanation.request
    result = request.result
    lines = [f"# AI explanation: {request.category_label or request.category} ({', '.join(result.processes)})", "",
             f"- Result: {Path(result.output_path).name}",
             f"- Explained: {explanation.created_at}" + (f" by {explanation.model}" if explanation.model else ""),
             "- Sent to Gemini: " + ("the result GeoTIFF, " if explanation.tif_attached else "") +
             f"{len(request.previews)} layer preview(s) and the metadata below", ""]

    def table(title: str, metadata: RasterMetadataDTO | None) -> None:
        if metadata is None:
            return
        lines.extend([f"## {title}", "", "| | |", "|---|---|"])
        lines.extend(f"| {label} | {value} |" for label, value in metadata.rows())
        lines.append("")

    table("Before the analysis: dataset", request.before)
    for index, other in enumerate(request.compared_with, start=1):
        table(f"Before the analysis: compared dataset {index}", other)
    table("After the analysis: result", request.after)
    if result.metrics:
        lines.extend(["## Numbers", "", "| | |", "|---|---|"])
        lines.extend(f"| {name} | {value:g} |" for name, value in result.metrics.items())
        lines.append("")
    lines.extend(["---", "", explanation.text.strip(), ""])
    return "\n".join(lines)
