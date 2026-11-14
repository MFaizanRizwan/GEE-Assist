"""Sentinel-1 radar (LULC analysis, "Radar (SAR)"): backscatter in dB, VV/VH ratio, radar vegetation index, RFDI and NDPI.

GEE's Sentinel-1 GRD bands are already in dB; the ratio indices convert them to
linear power first (see ``index_math``).
"""

from __future__ import annotations

from backend.business.analysis.raster_engine import LayerSpec


def special_layers(key, periods):
    """Backscatter in dB: one layer per polarisation the dataset has. None for other processes."""
    if key != "Backscatter_dB":
        return None
    layers = []
    for role in ("vv", "vh", "hh", "hv"):
        if role in periods[-1].roles:
            name = role.upper()
            layers.append(LayerSpec(f"{name}_dB", f"{name} backscatter",
                                    lambda block, role=role: block.roles()[role], "grey", "dB", -25.0, 0.0))
    return layers, [], []
