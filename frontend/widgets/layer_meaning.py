"""What a result layer's low and high values mean, in plain words, for its legend.

A colour bar with "-0.2 … 0.8" under it does not say what the colours *are*; this
adds "Bare ground / water" at the low end and "Dense, healthy vegetation" at the high
end. Looked up by the layer (index) name first, then by the colour style the analysis
drew it with. Layers with no clear meaning (raw bands, PCA, soil chemistry ratios)
get none, and their legend shows only the numbers.
"""

from __future__ import annotations

_LAND_WATER = ("Land", "Open water")

# By the index name (the layer id, e.g. "NDVI").
_BY_NAME: dict[str, tuple[str, str]] = {
    "NDWI": _LAND_WATER, "MNDWI": _LAND_WATER, "AWEInsh": _LAND_WATER, "AWEIsh": _LAND_WATER,
    "WRI": _LAND_WATER,
    "NDMI": ("Dry vegetation / soil", "Moist vegetation"),
    "LSWI": ("Dry surface", "Wet surface"),
    "NDII": ("Dry canopy", "Moist canopy"),
    "NBR": ("Burned / bare", "Healthy vegetation"),
    "NBR2": ("Dry / burned", "Moist vegetation"),
    "CSI": ("Burned / bare", "Healthy vegetation"),
    "PSRI": ("Green, healthy leaves", "Ageing / stressed leaves"),
    "BSI": ("Vegetated", "Bare soil"),
    "LST": ("Cooler surface", "Hotter surface"),
    "Backscatter_dB": ("Smooth (water, bare)", "Rough (crops, trees, buildings)"),
    "RVI_SAR": ("Bare / sparse", "Dense vegetation"),
    "RFDI": ("Intact forest", "Degraded / cleared"),
    "NDTI": ("Clear water", "Turbid water"),
}

# By the colour style the analysis drew the layer with.
_BY_STYLE: dict[str, tuple[str, str]] = {
    "vegetation": ("Bare ground / water", "Dense, healthy vegetation"),
    "water": ("Dry", "Wet / open water"),
    "dryness": ("Moist", "Dry / water-stressed"),
    "condition": ("Poor / stressed", "Good condition"),
    "burn": ("Unburned / regrowth", "Severely burned"),
    "turbidity": ("Clear water", "Turbid water"),
    "algae": ("Little algae", "Algal bloom"),
    "urban": ("Vegetation / water", "Built-up"),
    "snow": ("No snow", "Snow / ice"),
    "thermal": ("Cooler", "Hotter"),
}


def meaning(name: str, style: str = "") -> tuple[str, str] | None:
    """(what low values mean, what high values mean) for a layer, or None when unknown.

    ``name`` may carry more after the index ("NDVI (vegetation)", "NDVI 2024-01-01"):
    its first word is tried too.
    """
    name = (name or "").strip()
    for key in (name, name.split(" ")[0]):
        if key in _BY_NAME:
            return _BY_NAME[key]
    return _BY_STYLE.get(style or "")
