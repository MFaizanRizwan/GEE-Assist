"""Prompts for Gemini: turning a natural-language request into form parameters, and
explaining an analysis result (UC-08 Get AI Explanation)."""

from __future__ import annotations

import json
from datetime import date

from backend.config import ANALYSIS_CATEGORIES, COMPOSITE_METHODS, DATASETS
from backend.dto.explanation_dto import ExplanationRequestDTO, RasterMetadataDTO


def _catalogue() -> dict:
    return {
        key: {
            "name": info.name,
            "category": info.category,
            "bands": list(info.bands),
            "default_bands": list(info.default_bands),
            "default_scale_m": info.default_scale,
            "cloud_filter": info.supports_cloud_filter,
            "available": [info.min_date.isoformat(), info.max_date.isoformat() if info.max_date else "present"],
            "supported_analyses": {k: list(v) for k, v in info.supported_analyses.items()},
        }
        for key, info in DATASETS.items()
    }


def build_query_system_prompt(today: date | None = None) -> str:
    today = today or date.today()
    return f"""You fill in the data-request form of GEE-Assist, a desktop tool that downloads
satellite data from Google Earth Engine. Read the user's request and return the form values.

Today is {today.isoformat()}.

Supported datasets (answer with the KEY, e.g. "sentinel2_sr"):
{json.dumps(_catalogue(), indent=1)}

Analysis categories and their processes (optional; leave empty if the user only wants data):
{json.dumps({k: list(v) for k, v in ANALYSIS_CATEGORIES.items()}, indent=1)}

Composite methods: {", ".join(COMPOSITE_METHODS)}

Rules:
- dataset: the supported dataset that best fits the request, its time range and any analysis.
  Prefer sentinel2_sr for recent optical work, landsat8_l2/landsat9_l2 for thermal or older
  optical, sentinel1_grd for radar / cloudy-region water, dynamic_world for land cover.
- bands: only bands of the chosen dataset; use its default_bands if the user names none.
- start_date / end_date: YYYY-MM-DD. Resolve relative phrases ("last summer", "2020 to 2022",
  "past 3 months") against today. Keep them inside the dataset's availability. Empty if not given.
- aoi_name: the place the user mentions. aoi_bbox: its approximate WGS84 bounding box as
  [min_lon, min_lat, max_lon, max_lat]; keep it tight around the place. Empty list if no place.
- max_cloud_cover: 0-100 for datasets with cloud_filter when the user mentions clouds, else -1.
- scale_m: only if the user asks for a resolution, else 0.
- composite: only if the user asks (e.g. "average" -> mean), else "".
- analysis_type / processes: only if the user asks for an analysis; processes must be
  supported by the chosen dataset for that category.
- clarification: one short question if something essential (place or time) is missing or
  ambiguous, otherwise "". If the request is not about satellite data, leave every other
  field empty and explain in clarification.
- Never invent datasets, bands or processes outside the lists above.
- The request may end with "Entities recognised in this request": these come from a classifier run
  on the user's text. Treat DATASET, PROCESS, BAND, CLOUD_COVER, RESOLUTION and COMPOSITE entries as
  the user's explicit choices, use PLACE entries for aoi_name / aoi_bbox, and use a DATE value
  (YYYY-MM-DD/YYYY-MM-DD) when one is given.
"""


# ----------------------------------------------------------------------------- explanation
EXPLANATION_SYSTEM_PROMPT = """You are a remote-sensing analyst inside GEE-Assist, a desktop app that
downloads satellite imagery from Google Earth Engine and analyses it on the user's computer.
Explain one analysis result to the user, who may not be a remote-sensing expert.

You are given which analysis ran and with which settings, the metadata of the dataset before the
analysis (and of any earlier dataset it was compared with), the metadata of the result GeoTIFF
after the analysis, the numbers it produced, the result GeoTIFF itself (one band per layer,
no-data = -9999) when it could be attached, and a PNG preview of each layer coloured as described.

Answer in Markdown with these sections, leaving out any that do not apply:
## Summary            two or three sentences: what the result says about this place and time
## What was measured  each process in plain words: what it measures and how to read its values
## What the results show   the numbers, read against the usual ranges; cite the values given
## Where               spatial patterns visible in the previews (which parts are high or low)
## Before and after    for change processes only: what changed between the dates
## Reliability         caveats from the metadata: dates, season, clouds, resolution, sensor, notes
## Next steps          two or three concrete follow-ups the user could run in GEE-Assist

Rules:
- Use only the numbers and metadata given; never invent values, places or dates.
- Say when something cannot be told from the data (e.g. the cause of a change).
- Keep it under about 450 words. Use units. No preamble, no closing remarks.
"""


def _metadata_lines(metadata: RasterMetadataDTO) -> list[str]:
    return [f"- {label}: {value}" for label, value in metadata.rows()]


def build_explanation_prompt(request: ExplanationRequestDTO) -> str:
    """The user prompt sent with the result GeoTIFF and its previews."""
    result = request.result
    label = request.category_label or request.category
    lines = ["Explain this GEE-Assist analysis result.", "", "# Analysis that was run",
             f"- Analysis: {label}" + (f" ({request.category})" if label != request.category else "")]
    lines.append("- Processes:")
    for process in request.processes:
        details = "; ".join(part for part in (
            process.name, f"formula {process.formula}" if process.formula else "",
            f"range {process.value_range}" if process.value_range else "",
            f"how to read it: {process.interpretation}" if process.interpretation else "") if part)
        lines.append(f"  - {process.key}" + (f": {details}" if details else ""))
    if request.params:
        lines.append("- Parameters: " + ", ".join(f"{key} = {value}" for key, value in request.params.items()))
    run = [part for part in (result.device and f"on {result.device}",
                             result.seconds and f"in {result.seconds:.1f} s",
                             result.created_at and f"at {result.created_at}") if part]
    if run:
        lines.append("- Ran " + " ".join(run))

    lines += ["", "# Metadata before the analysis (the dataset analysed)"]
    lines += _metadata_lines(request.before) if request.before else ["- Not available"]
    for index, other in enumerate(request.compared_with, start=1):
        lines += ["", f"# Metadata before the analysis: compared dataset {index} (earlier date)"]
        lines += _metadata_lines(other)

    lines += ["", "# Metadata after the analysis (the result GeoTIFF)"]
    lines += _metadata_lines(request.after) if request.after else ["- Not available"]
    if request.layers:
        lines.append("- Layers (one band each, in this order):")
        for number, layer in enumerate(request.layers, start=1):
            unit = f" [{layer.unit}]" if layer.unit else ""
            legend = f": preview coloured {layer.legend}" if layer.legend else ""
            lines.append(f"  {number}. {layer.key} ({layer.label}){unit}{legend}")

    lines += ["", "# Numbers the analysis produced"]
    lines += [f"- {name}: {value:g}" if isinstance(value, (int, float)) else f"- {name}: {value}"
              for name, value in result.metrics.items()] or ["- None"]
    if result.notes:
        lines += ["", "# Notes from the analysis"] + [f"- {note}" for note in result.notes]

    attached = []
    if request.tif_path:
        attached.append(f"- The result GeoTIFF {request.after.name if request.after else ''}.tif (if accepted)")
    if request.previews:
        names = ", ".join(layer.key for layer in request.layers[:len(request.previews)])
        attached.append(f"- {len(request.previews)} PNG preview(s), one per layer, in this order: {names}")
    if attached:
        lines += ["", "# Attached"] + attached
    return "\n".join(lines)
