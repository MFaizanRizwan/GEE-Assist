"""Sentinel-1 radar: backscatter in dB, VV/VH ratio, radar vegetation index, RFDI and NDPI.

GEE's Sentinel-1 GRD bands are already in dB; the ratio indices convert them to
linear power first (see ``index_math``).
"""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis
from backend.business.analysis.raster_engine import LayerSpec


class SARAnalysis(BaseAnalysis):
    CATEGORY = "SAR (radar)"

    def _special_layers(self, key, periods, params, notes):
        if key != "Backscatter_dB":
            return None
        layers = []
        for role in ("vv", "vh", "hh", "hv"):
            if role in periods[-1].roles:
                name = role.upper()
                layers.append(LayerSpec(f"{name}_dB", f"{name} backscatter",
                                        lambda block, role=role: block.roles()[role], "grey", "dB", -25.0, 0.0))
        return layers, [], []
