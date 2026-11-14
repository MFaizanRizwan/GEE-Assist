"""Class diagram: WaterAnalysis. NDWI, MNDWI, AWEI, WRI, turbidity, chlorophyll, floating algae,
water-body detection and water-area estimation (FR-06).

The water mask comes from the best source the dataset has:

* JRC Global Surface Water: its own classes (2 = water, 1 = land, 0 = not observed);
* Sentinel-1 radar: VV backscatter below ``sar_water_db`` (−16 dB by default), as calm
  water reflects the radar away from the satellite;
* optical: MNDWI above ``water_threshold`` (0 by default), or NDWI without a SWIR band.
"""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis
from backend.business.analysis.index_math import nd
from backend.business.analysis.raster_engine import Accumulator, LayerSpec, Period

MASK_PROCESSES = ("WaterBodyDetection", "WaterAreaEstimation")
DEFAULT_SAR_WATER_DB = -16.0


def water_source(period: Period) -> str:
    """"jrc", "sar", "mndwi", "ndwi" or "" (no way to find water)."""
    if period.satellite == "JRC-GSW" and "water" in period.band_names:
        return "jrc"
    if "vv" in period.roles:
        return "sar"
    if {"green", "swir1"} <= period.roles.keys():
        return "mndwi"
    if {"green", "nir"} <= period.roles.keys():
        return "ndwi"
    return ""


def water_mask(block, source: str, params: dict):
    """1 where there is water, 0 where there is land, NaN without data."""
    xp = block.xp
    nan = xp.float32(float("nan"))
    if source == "jrc":
        classes = block.band("water", scaled=False)
        return xp.where(classes == 2, 1.0, xp.where(classes == 1, 0.0, nan)).astype(xp.float32)
    if source == "sar":
        vv = block.roles()["vv"]
        value, threshold = vv, float(params.get("sar_water_db", DEFAULT_SAR_WATER_DB))
        return xp.where(xp.isnan(value), nan, (value < threshold).astype(xp.float32))
    b = block.roles()
    value = nd(b["green"], b["swir1"]) if source == "mndwi" else nd(b["green"], b["nir"])
    threshold = float(params.get("water_threshold", 0.0))
    return xp.where(xp.isfinite(value), (value > threshold).astype(xp.float32), nan)


class WaterArea(Accumulator):
    """Area of the water pixels, and their share of the pixels with data."""

    def __init__(self, layer_key: str):
        self.key = layer_key
        self.water_km2 = self.valid_km2 = 0.0

    def add(self, block, outputs) -> None:
        xp, mask = block.xp, outputs[self.key]
        area = xp.broadcast_to(block.pixel_area_km2, mask.shape)
        valid = xp.isfinite(mask)
        self.water_km2 += block.backend.scalar(xp.sum(xp.where(valid & (mask > 0.5), area, 0.0)))
        self.valid_km2 += block.backend.scalar(xp.sum(xp.where(valid, area, 0.0)))

    def metrics(self) -> dict[str, float]:
        share = 100.0 * self.water_km2 / self.valid_km2 if self.valid_km2 else 0.0
        return {"Water area (km²)": self.water_km2, "Water share of the area (%)": share,
                "Area with data (km²)": self.valid_km2}


class WaterAnalysis(BaseAnalysis):
    CATEGORY = "Water"

    def _special_check(self, formula, period):
        if formula.key not in MASK_PROCESSES:
            return ""
        return None if water_source(period) else "Needs green and NIR or SWIR1 bands, or radar (VV) data."

    def _special_layers(self, key, periods, params, notes):
        if key not in MASK_PROCESSES:
            return None
        source = water_source(periods[-1])
        how = {"jrc": "JRC water classes", "sar": f"VV < {params.get('sar_water_db', DEFAULT_SAR_WATER_DB)} dB",
               "mndwi": f"MNDWI > {params.get('water_threshold', 0.0)}",
               "ndwi": f"NDWI > {params.get('water_threshold', 0.0)}"}[source]
        note = f"Water mask from {how}."
        if note not in notes:
            notes.append(note)
        layer = LayerSpec("Water", "Water mask", lambda block: water_mask(block, source, params), "mask",
                          low=0.0, high=1.0, stats=False)
        accumulators = [WaterArea("Water")] if key == "WaterAreaEstimation" else []
        return [layer], [], accumulators
