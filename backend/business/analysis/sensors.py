"""What the numbers in a downloaded GeoTIFF mean, per satellite.

Downloads hold the collection's raw values (see ``GEEClient``: ``toFloat`` only), so
before an index is computed each band is turned into a physical quantity:

* optical bands -> surface reflectance, 0 to 1 (``reflectance = raw × scale + offset``);
* thermal bands -> surface temperature in kelvin;
* Sentinel-1 bands are already backscatter in dB; class bands are class numbers.

Normalised differences such as NDVI do not care about a common scale, but EVI, SAVI,
BAI, the AWEIs and the Landsat offset (−0.2) do, so the scaling is always applied.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.business.download.naming import parse_dataset_name
from backend.config import DATASETS
from backend.dto.download_dto import DatasetDTO

NODATA = -9999.0  # what downloads (and analysis results) use for "no data"

# satellite -> band name pattern -> (scale, offset). The first matching pattern wins.
_SCALING: dict[str, tuple[tuple[str, float, float], ...]] = {
    "Sentinel-2": ((r"B\d+A?", 0.0001, 0.0),),
    "Landsat-8": ((r"SR_B\d+", 0.0000275, -0.2), (r"ST_B\d+", 0.00341802, 149.0)),
    "Landsat-9": ((r"SR_B\d+", 0.0000275, -0.2), (r"ST_B\d+", 0.00341802, 149.0)),
    "Landsat-7": ((r"SR_B\d+", 0.0000275, -0.2), (r"ST_B\d+", 0.00341802, 149.0)),
    "Landsat-5": ((r"SR_B\d+", 0.0000275, -0.2), (r"ST_B\d+", 0.00341802, 149.0)),
    "MODIS-Terra": ((r"sur_refl_b\d+", 0.0001, 0.0), (r"LST_(Day|Night)_1km", 0.02, 0.0),
                    (r"NDVI|EVI", 0.0001, 0.0)),
    "MODIS-Aqua": ((r"LST_(Day|Night)_1km", 0.02, 0.0),),
}

# Land-cover class bands: satellite -> (band, class table key).
CLASS_BANDS: dict[str, tuple[str, str]] = {
    "Dynamic-World": ("label", "dynamic_world"),
    "MODIS": ("LC_Type1", "modis_igbp"),
}

# Bands that already hold a product (e.g. MOD13Q1's NDVI): satellite -> {process: band}.
PRODUCT_BANDS: dict[str, dict[str, str]] = {
    "MODIS-Terra": {"NDVI": "NDVI", "EVI": "EVI"},
}

_BY_COLLECTION = {info.collection_id: info.satellite for info in DATASETS.values() if info.satellite}


def resolve_satellite(dataset: DatasetDTO, band_names: tuple[str, ...] = ()) -> str:
    """The satellite a dataset comes from: as recorded, from its GEE collection, its file name, or its bands."""
    if dataset.satellite:
        return dataset.satellite
    if dataset.source in _BY_COLLECTION:
        return _BY_COLLECTION[dataset.source]
    satellite, _, _ = parse_dataset_name(Path(dataset.path).stem)
    if satellite in _SCALING or satellite in CLASS_BANDS or satellite in ("Sentinel-1", "ERA5-Land", "JRC-GSW"):
        return satellite
    return _guess_from_bands(tuple(band_names) or tuple(dataset.bands))


def _guess_from_bands(names: tuple[str, ...]) -> str:
    present = set(names)
    if {"B2", "B3", "B4"} <= present:
        return "Sentinel-2"
    if any(name.startswith("sur_refl_b") for name in present) or "LST_Day_1km" in present:
        return "MODIS-Terra"
    if {"VV", "VH"} & present:
        return "Sentinel-1"
    if "label" in present:
        return "Dynamic-World"
    if "LC_Type1" in present:
        return "MODIS"
    if "skin_temperature" in present:
        return "ERA5-Land"
    if present == {"water"}:
        return "JRC-GSW"
    return ""


def scaling(satellite: str, band: str) -> tuple[float, float]:
    """(scale, offset) turning ``band``'s raw values into reflectance or kelvin; (1, 0) when unknown."""
    for pattern, scale, offset in _SCALING.get(satellite, ()):
        if re.fullmatch(pattern, band):
            return scale, offset
    return 1.0, 0.0


def class_band(satellite: str, band_names: tuple[str, ...]) -> tuple[str, str] | None:
    """(band, class table key) of a land-cover dataset, if it has its class band."""
    entry = CLASS_BANDS.get(satellite)
    if entry is None:  # e.g. a renamed file: recognise the band itself
        entry = next((value for value in CLASS_BANDS.values() if value[0] in band_names), None)
    return entry if entry and entry[0] in band_names else None
