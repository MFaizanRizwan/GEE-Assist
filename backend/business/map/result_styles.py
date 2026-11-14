"""How an analysis result's bands are coloured on the Analysis page, so the viewer can show them the same way.

The analysis writes ``<result>.json`` next to its GeoTIFF. Newer summaries hold each layer's colour
style and range (``styles``); older ones only name the layers, whose colours are then taken from the
index table where it knows them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.dto.result_dto import ResultLayerDTO

logger = logging.getLogger(__name__)


def read_result_layers(tif_path: str | Path, band_names: tuple[str, ...]) -> tuple[ResultLayerDTO, ...]:
    """The analysis layers of the GeoTIFF at ``tif_path`` that are among ``band_names``; () if it is not a result."""
    summary_path = Path(tif_path).with_suffix(".json")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, ValueError):
        logger.warning("Cannot read the analysis summary %s", summary_path, exc_info=True)
        return ()
    if not isinstance(summary, dict) or "category" not in summary or "layers" not in summary:
        return ()  # some other JSON that happens to sit next to the file

    present = set(band_names)
    styles = summary.get("styles")
    if isinstance(styles, list):
        layers = []
        for item in styles:
            try:
                layer = ResultLayerDTO(**{key: item[key] for key in ResultLayerDTO.__dataclass_fields__ if key in item})
            except (TypeError, KeyError):
                continue
            if layer.key in present:
                layers.append(layer)
        return tuple(layers)
    return tuple(_from_index_table(key) for key in summary.get("layers", []) if key in present)


def _from_index_table(key: str) -> ResultLayerDTO:
    """A layer of an older result: the index table's colours, or a plain stretched scale for other layers."""
    from backend.business.analysis.index_math import INDEX_FUNCTIONS

    definition = INDEX_FUNCTIONS.get(key)
    if definition is None:
        return ResultLayerDTO(key, key, "diverging")
    return ResultLayerDTO(key, key, definition.style, definition.unit, definition.low, definition.high)
