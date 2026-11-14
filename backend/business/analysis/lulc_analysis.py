"""Class diagram: LULCAnalysis. Land-cover change between two maps of the same place (FR-08).

Works on Dynamic World (``label``, classes 0-8) and MODIS MCD12Q1 (``LC_Type1``, IGBP
classes 1-17). The earliest dataset is "before", the latest "after".

* Change detection writes a transition code per pixel: ``before × 100 + after``
  (unchanged pixels have before = after), drawn grey when unchanged and in the new
  class's colour when changed.
* The transition matrix adds up the area of every "from → to" pair; its layer holds
  the class each changed pixel used to be.
"""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis
from backend.business.analysis.raster_engine import Accumulator, LayerSpec, Period
from backend.business.analysis.sensors import class_band
from backend.business.map.colour_maps import class_name
from backend.exceptions import AnalysisError

CODE_BASE = 100
MAX_TRANSITIONS_SHOWN = 30


def _classes(block, period: int, band: str):
    return block.band(band, period, scaled=False)


class Transitions(Accumulator):
    """km² of each (before, after) class pair."""

    def __init__(self, table: str, code_key: str):
        self.table, self.code_key = table, code_key
        self.dedupe_key = code_key
        self.areas: dict[int, float] = {}

    def add(self, block, outputs) -> None:
        xp = block.xp
        codes = outputs[self.code_key]
        area = xp.broadcast_to(block.pixel_area_km2, codes.shape)
        valid = xp.isfinite(codes)
        if not bool(valid.any()):
            return
        values = codes[valid].astype(xp.int64)
        sums = xp.bincount(values, weights=area[valid].astype(xp.float64))
        found = block.backend.to_host(xp.nonzero(sums)[0])
        totals = block.backend.to_host(sums)
        for code in found.tolist():
            self.areas[code] = self.areas.get(code, 0.0) + float(totals[code])

    def metrics(self) -> dict[str, float]:
        total = sum(self.areas.values())
        changed = {code: km2 for code, km2 in self.areas.items() if code // CODE_BASE != code % CODE_BASE}
        changed_km2 = sum(changed.values())
        metrics = {"Area compared (km²)": total, "Changed area (km²)": changed_km2,
                   "Changed share of the area (%)": 100.0 * changed_km2 / total if total else 0.0}
        for code, km2 in sorted(changed.items(), key=lambda item: -item[1])[:MAX_TRANSITIONS_SHOWN]:
            before, after = class_name(self.table, code // CODE_BASE), class_name(self.table, code % CODE_BASE)
            metrics[f"{before} → {after} (km²)"] = km2
        return metrics


class LULCAnalysis(BaseAnalysis):
    CATEGORY = "Land cover"

    def _special_check(self, formula, period: Period):
        if formula.key not in ("LULCChangeDetection", "LULCTransition"):
            return ""
        if class_band(period.satellite, period.band_names) is None:
            return "Needs a land-cover map: Dynamic World (label band) or MODIS land cover (LC_Type1)."
        return None

    def _special_layers(self, key, periods, params, notes):
        if key not in ("LULCChangeDetection", "LULCTransition"):
            return None
        found = [class_band(period.satellite, period.band_names) for period in periods]
        band, table = found[-1]
        if any(entry != (band, table) for entry in found):
            raise AnalysisError("Both datasets must be the same kind of land-cover map (both Dynamic World, or "
                                "both MODIS land cover).")
        if periods[0].date and periods[-1].date and periods[0].date == periods[-1].date:
            notes.append("Both datasets start on the same date: the change may only be noise.")

        def codes(block):
            xp = block.xp
            before, after = _classes(block, 0, band), _classes(block, -1, band)
            return xp.where(xp.isnan(before) | xp.isnan(after), xp.float32(float("nan")),
                            xp.round(before) * CODE_BASE + xp.round(after))

        code_layer = LayerSpec("LULC_change", "Land-cover change", codes, "transition", classes=table, stats=False)
        accumulators = [Transitions(table, "LULC_change")]
        if key == "LULCChangeDetection":
            return [code_layer], [], accumulators

        def lost(block):
            xp = block.xp
            before, after = _classes(block, 0, band), _classes(block, -1, band)
            return xp.where(xp.round(before) != xp.round(after), before, xp.float32(float("nan")))

        lost_layer = LayerSpec("LULC_from", "Class before the change", lost, "classes", classes=table, stats=False)
        return [code_layer, lost_layer], [], accumulators
