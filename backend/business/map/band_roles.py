"""Which band of a download is blue, green, red, near-infrared or short-wave infrared.

Band names alone are not enough: Landsat 8/9 and Landsat 5/7 use the same names for
different colours (``SR_B2`` is blue on Landsat 8, green on Landsat 5). So the
satellite in the download's name decides; for a file from elsewhere, Sentinel-2 and
MODIS band names are recognised on their own.

``band_roles`` gives the five roles the viewer uses (``ROLES``). The analyses need
more of them (red edge, a second SWIR band, thermal, radar polarisations), so
``ALL_ROLES`` lists every role the tables know; pass it as ``roles`` to get them.
"""

from __future__ import annotations

ROLES = ("blue", "green", "red", "nir", "swir1")

# Every role, in wavelength order. "re1" to "re3" are the red-edge bands, "nir2" the
# narrow NIR band (Sentinel-2 B8A), "thermal" a thermal-infrared or surface-temperature band.
ALL_ROLES = ("coastal", "blue", "green", "red", "re1", "re2", "re3", "nir", "nir2", "swir1", "swir2",
             "thermal", "vv", "vh", "hh", "hv")

_SENTINEL_2 = {"coastal": "B1", "blue": "B2", "green": "B3", "red": "B4", "re1": "B5", "re2": "B6", "re3": "B7",
               "nir": "B8", "nir2": "B8A", "swir1": "B11", "swir2": "B12"}
_LANDSAT_8_9 = {"coastal": "SR_B1", "blue": "SR_B2", "green": "SR_B3", "red": "SR_B4", "nir": "SR_B5",
                "swir1": "SR_B6", "swir2": "SR_B7", "thermal": "ST_B10"}
_LANDSAT_5_7 = {"blue": "SR_B1", "green": "SR_B2", "red": "SR_B3", "nir": "SR_B4", "swir1": "SR_B5",
                "swir2": "SR_B7", "thermal": "ST_B6"}
_MODIS = {"blue": "sur_refl_b03", "green": "sur_refl_b04", "red": "sur_refl_b01", "nir": "sur_refl_b02",
          "swir1": "sur_refl_b06", "swir2": "sur_refl_b07"}
_MODIS_LST = {"thermal": "LST_Day_1km"}
_ERA5 = {"thermal": "skin_temperature"}
_SENTINEL_1 = {"vv": "VV", "vh": "VH", "hh": "HH", "hv": "HV"}

_BY_SATELLITE = {
    "Sentinel-2": _SENTINEL_2,
    "Landsat-8": _LANDSAT_8_9,
    "Landsat-9": _LANDSAT_8_9,
    "Landsat-5": _LANDSAT_5_7,
    "Landsat-7": _LANDSAT_5_7,
    "MODIS-Terra": {**_MODIS, **_MODIS_LST},
    "MODIS-Aqua": _MODIS_LST,
    "ERA5-Land": _ERA5,
    "Sentinel-1": _SENTINEL_1,
}


def band_roles(satellite: str, band_names: tuple[str, ...], roles: tuple[str, ...] = ROLES) -> dict[str, str]:
    """Role (``"red"``, ``"nir"``, ...) -> band name, for the ``roles`` this file has."""
    table = _BY_SATELLITE.get(satellite) or _guess_table(band_names)
    if not table:
        return {}
    present = set(band_names)
    return {role: band for role, band in table.items() if band in present and role in roles}


def _guess_table(band_names: tuple[str, ...]) -> dict[str, str]:
    names = set(band_names)
    if {"B2", "B3", "B4"} <= names:
        return _SENTINEL_2
    if any(name.startswith("sur_refl_b") for name in names):
        return _MODIS
    if "LST_Day_1km" in names:
        return _MODIS_LST
    if "skin_temperature" in names:
        return _ERA5
    if {"VV", "VH"} & names:
        return _SENTINEL_1
    return {}  # e.g. Landsat without its satellite: the names are ambiguous
