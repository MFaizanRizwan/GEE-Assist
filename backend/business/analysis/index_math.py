"""The arithmetic of every computable index in the formula catalogue, keyed like it.

Each function gets ``xp`` (NumPy on the CPU, CuPy on the GPU: the same code runs on
both), ``b`` (band role -> array of reflectance / kelvin / dB for one block of rows)
and ``p`` (parameters, plus ``p["scene"]`` for indices that need the whole dataset's
range first, and ``p["before"]`` with the earlier period's bands for change indices).

Divisions by zero give inf / NaN; the engine turns every non-finite result into no-data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

Fn = Callable[[Any, dict, dict], Any]

# Centre wavelengths (nm) used by the Floating Algae Index baseline.
_FAI_RED, _FAI_NIR, _FAI_SWIR = 665.0, 842.0, 1610.0


@dataclass(frozen=True)
class IndexDef:
    roles: tuple[str, ...]                      # band roles it reads
    fn: Fn
    scene: tuple[str, ...] = ()                 # quantities whose dataset-wide min/max it needs ("NDVI", "thermal")
    low: float | None = None                    # fixed display range (None: stretched to the data)
    high: float | None = None
    style: str = "diverging"                    # colour style (see backend/business/map/layer_styles.py)
    unit: str = ""


def nd(a, b):
    """Normalised difference (a − b) / (a + b)."""
    return (a - b) / (a + b)


def _ndvi(xp, b, p):
    return nd(b["nir"], b["red"])


def _evi(xp, b, p):
    return 2.5 * (b["nir"] - b["red"]) / (b["nir"] + 6.0 * b["red"] - 7.5 * b["blue"] + 1.0)


def _savi(xp, b, p):
    l_ = float(p.get("savi_l", 0.5))
    return (1.0 + l_) * (b["nir"] - b["red"]) / (b["nir"] + b["red"] + l_)


def _msavi(xp, b, p):
    nir, red = b["nir"], b["red"]
    return (2.0 * nir + 1.0 - xp.sqrt(xp.maximum((2.0 * nir + 1.0) ** 2 - 8.0 * (nir - red), 0.0))) / 2.0


def _wdrvi(xp, b, p):
    a = float(p.get("wdrvi_alpha", 0.1))
    return (a * b["nir"] - b["red"]) / (a * b["nir"] + b["red"])


def _mcari(xp, b, p):
    re1, red, green = b["re1"], b["red"], b["green"]
    return ((re1 - red) - 0.2 * (re1 - green)) * (re1 / red)


def _tcari(xp, b, p):
    re1, red, green = b["re1"], b["red"], b["green"]
    return 3.0 * ((re1 - red) - 0.2 * (re1 - green) * (re1 / red))


def _arvi(xp, b, p):
    rb = 2.0 * b["red"] - b["blue"]
    return (b["nir"] - rb) / (b["nir"] + rb)


def _fcover(xp, b, p):
    soil, veg = float(p.get("fcover_ndvi_soil", 0.2)), float(p.get("fcover_ndvi_veg", 0.86))
    return xp.clip((_ndvi(xp, b, p) - soil) / (veg - soil), 0.0, 1.0) ** 2


def _ndmi(xp, b, p):
    return nd(b["nir"], b["swir1"])


def _nddi(xp, b, p):
    ndvi, ndwi = _ndvi(xp, b, p), _ndmi(xp, b, p)
    return (ndvi - ndwi) / (ndvi + ndwi)


def _scaled(value, low_high, invert: bool = False):
    low, high = low_high
    span = high - low if high > low else 1.0
    return 100.0 * ((high - value) if invert else (value - low)) / span


def _vci(xp, b, p):
    return _scaled(_ndvi(xp, b, p), p["scene"]["NDVI"])


def _tci(xp, b, p):
    return _scaled(b["thermal"], p["scene"]["thermal"], invert=True)


def _vhi(xp, b, p):
    return 0.5 * _vci(xp, b, p) + 0.5 * _tci(xp, b, p)


def _nbr(xp, b, p):
    return nd(b["nir"], b["swir2"])


def _dnbr(xp, b, p):
    return _nbr(xp, p["before"], p) - _nbr(xp, b, p)


def _rdnbr(xp, b, p):
    pre = _nbr(xp, p["before"], p)
    return (pre - _nbr(xp, b, p)) / xp.sqrt(xp.maximum(xp.abs(pre), 0.001))


def _rbr(xp, b, p):
    pre = _nbr(xp, p["before"], p)
    return (pre - _nbr(xp, b, p)) / (pre + 1.001)


def _ibi(xp, b, p):
    swir1, nir, red, green = b["swir1"], b["nir"], b["red"], b["green"]
    built = 2.0 * swir1 / (swir1 + nir)
    other = nir / (nir + red) + green / (green + swir1)
    return (built - other) / (built + other)


def _fai(xp, b, p):
    red, nir, swir = b["red"], b["nir"], b["swir1"]
    return nir - (red + (swir - red) * (_FAI_NIR - _FAI_RED) / (_FAI_SWIR - _FAI_RED))


def _db_to_linear(xp, db):
    return 10.0 ** (db / 10.0)


def _rvi_sar(xp, b, p):
    vv, vh = _db_to_linear(xp, b["vv"]), _db_to_linear(xp, b["vh"])
    return 4.0 * vh / (vv + vh)


def _ndpi(xp, b, p):
    return nd(_db_to_linear(xp, b["vv"]), _db_to_linear(xp, b["vh"]))


def _rfdi(xp, b, p):
    return nd(_db_to_linear(xp, b["hh"]), _db_to_linear(xp, b["hv"]))


def _d(roles: str, fn: Fn, **more) -> IndexDef:
    return IndexDef(tuple(roles.split()), fn, **more)


_VEG = dict(style="vegetation")
_WET = dict(style="water")

INDEX_FUNCTIONS: dict[str, IndexDef] = {
    # vegetation
    "NDVI": _d("nir red", _ndvi, low=-0.2, high=0.8, **_VEG),
    "EVI": _d("nir red blue", _evi, low=-0.2, high=0.8, **_VEG),
    "SAVI": _d("nir red", _savi, low=-0.2, high=0.8, **_VEG),
    "MSAVI": _d("nir red", _msavi, low=-0.2, high=0.8, **_VEG),
    "GNDVI": _d("nir green", lambda xp, b, p: nd(b["nir"], b["green"]), low=-0.2, high=0.8, **_VEG),
    "NDRE": _d("nir re1", lambda xp, b, p: nd(b["nir"], b["re1"]), low=-0.1, high=0.6, **_VEG),
    "GCI": _d("nir green", lambda xp, b, p: b["nir"] / b["green"] - 1.0, low=0.0, high=8.0, **_VEG),
    "CIre": _d("nir re1", lambda xp, b, p: b["nir"] / b["re1"] - 1.0, low=0.0, high=6.0, **_VEG),
    "MTCI": _d("re2 re1 red", lambda xp, b, p: (b["re2"] - b["re1"]) / (b["re1"] - b["red"]), low=0.0, high=6.0,
               **_VEG),
    "MCARI": _d("re1 red green", _mcari, **_VEG),
    "TCARI": _d("re1 red green", _tcari, **_VEG),
    "ARVI": _d("nir red blue", _arvi, low=-0.2, high=0.8, **_VEG),
    "VARI": _d("green red blue", lambda xp, b, p: (b["green"] - b["red"]) / (b["green"] + b["red"] - b["blue"]),
               low=-0.5, high=0.5, **_VEG),
    "RVI": _d("nir red", lambda xp, b, p: b["nir"] / b["red"], low=0.0, high=10.0, **_VEG),
    "DVI": _d("nir red", lambda xp, b, p: b["nir"] - b["red"], low=-0.1, high=0.5, **_VEG),
    "WDRVI": _d("nir red", _wdrvi, low=-0.8, high=0.4, **_VEG),
    "PSRI": _d("red blue re2", lambda xp, b, p: (b["red"] - b["blue"]) / b["re2"], low=-0.2, high=0.4,
               style="diverging"),
    "LAI": _d("nir red blue", lambda xp, b, p: xp.maximum(3.618 * _evi(xp, b, p) - 0.118, 0.0), low=0.0, high=6.0,
              unit="m²/m²", **_VEG),
    "FAPAR": _d("nir red", lambda xp, b, p: xp.clip(1.1638 * _ndvi(xp, b, p) - 0.1426, 0.0, 1.0), low=0.0,
                high=1.0, **_VEG),
    "FCover": _d("nir red", _fcover, low=0.0, high=1.0, **_VEG),
    # moisture & drought
    "NDMI": _d("nir swir1", _ndmi, low=-0.5, high=0.6, **_WET),
    "LSWI": _d("nir swir1", _ndmi, low=-0.5, high=0.6, **_WET),
    "NDII": _d("nir swir1", _ndmi, low=-0.5, high=0.6, **_WET),
    "MSI": _d("swir1 nir", lambda xp, b, p: b["swir1"] / b["nir"], low=0.2, high=2.5, style="dryness"),
    "NDDI": _d("nir red swir1", _nddi, low=-1.0, high=1.0, style="dryness"),
    "VCI": _d("nir red", _vci, scene=("NDVI",), low=0.0, high=100.0, style="condition"),
    "TCI": _d("thermal", _tci, scene=("thermal",), low=0.0, high=100.0, style="condition"),
    "VHI": _d("nir red thermal", _vhi, scene=("NDVI", "thermal"), low=0.0, high=100.0, style="condition"),
    # water
    "NDWI": _d("green nir", lambda xp, b, p: nd(b["green"], b["nir"]), low=-0.5, high=0.5, **_WET),
    "MNDWI": _d("green swir1", lambda xp, b, p: nd(b["green"], b["swir1"]), low=-0.6, high=0.6, **_WET),
    "AWEInsh": _d("green swir1 nir swir2",
                  lambda xp, b, p: 4.0 * (b["green"] - b["swir1"]) - (0.25 * b["nir"] + 2.75 * b["swir2"]),
                  low=-2.0, high=1.0, **_WET),
    "AWEIsh": _d("blue green nir swir1 swir2",
                 lambda xp, b, p: b["blue"] + 2.5 * b["green"] - 1.5 * (b["nir"] + b["swir1"]) - 0.25 * b["swir2"],
                 low=-1.0, high=0.5, **_WET),
    "WRI": _d("green red nir swir1", lambda xp, b, p: (b["green"] + b["red"]) / (b["nir"] + b["swir1"]),
              low=0.0, high=2.0, **_WET),
    "NDTI": _d("red green", lambda xp, b, p: nd(b["red"], b["green"]), low=-0.3, high=0.3, style="turbidity"),
    "NDCI": _d("re1 red", lambda xp, b, p: nd(b["re1"], b["red"]), low=-0.2, high=0.4, style="algae"),
    "FAI": _d("nir red swir1", _fai, low=-0.05, high=0.15, style="algae"),
    # burn
    "NBR": _d("nir swir2", _nbr, low=-0.5, high=0.8, **_VEG),
    "dNBR": _d("nir swir2", _dnbr, low=-0.5, high=1.0, style="burn"),
    "RdNBR": _d("nir swir2", _rdnbr, low=-0.5, high=2.0, style="burn"),
    "RBR": _d("nir swir2", _rbr, low=-0.3, high=0.8, style="burn"),
    "NBR2": _d("swir1 swir2", lambda xp, b, p: nd(b["swir1"], b["swir2"]), low=-0.2, high=0.4, style="diverging"),
    "BAI": _d("red nir", lambda xp, b, p: 1.0 / ((0.1 - b["red"]) ** 2 + (0.06 - b["nir"]) ** 2), low=0.0,
              high=250.0, style="burn"),
    "CSI": _d("nir swir2", lambda xp, b, p: b["nir"] / b["swir2"], low=0.5, high=4.0, **_VEG),
    # soil & salinity
    "BSI": _d("swir1 red nir blue",
              lambda xp, b, p: nd(b["swir1"] + b["red"], b["nir"] + b["blue"]), low=-0.4, high=0.4, style="soil"),
    "SI1": _d("green red", lambda xp, b, p: xp.sqrt(xp.maximum(b["green"] * b["red"], 0.0)), low=0.0, high=0.4,
              style="soil"),
    "SI2": _d("green red nir", lambda xp, b, p: xp.sqrt(b["green"] ** 2 + b["red"] ** 2 + b["nir"] ** 2), low=0.0,
              high=0.7, style="soil"),
    "SI3": _d("green red", lambda xp, b, p: xp.sqrt(b["green"] ** 2 + b["red"] ** 2), low=0.0, high=0.6,
              style="soil"),
    "SI_T": _d("red nir", lambda xp, b, p: 100.0 * b["red"] / b["nir"], low=0.0, high=150.0, style="soil"),
    "NDSI_salinity": _d("red nir", lambda xp, b, p: nd(b["red"], b["nir"]), low=-0.6, high=0.3, style="soil"),
    "BI": _d("red nir", lambda xp, b, p: xp.sqrt((b["red"] ** 2 + b["nir"] ** 2) / 2.0), low=0.0, high=0.5,
             style="soil"),
    "ClayIndex": _d("swir1 swir2", lambda xp, b, p: b["swir1"] / b["swir2"], low=0.8, high=2.0, style="soil"),
    "IronOxide": _d("red blue", lambda xp, b, p: b["red"] / b["blue"], low=0.5, high=3.0, style="soil"),
    "NDTI_tillage": _d("swir1 swir2", lambda xp, b, p: nd(b["swir1"], b["swir2"]), low=-0.1, high=0.4,
                       style="soil"),
    "CRC": _d("swir1 green", lambda xp, b, p: nd(b["swir1"], b["green"]), low=-0.2, high=0.6, style="soil"),
    "NDRI": _d("red swir2", lambda xp, b, p: nd(b["red"], b["swir2"]), low=-0.6, high=0.2, style="soil"),
    # built-up
    "NDBI": _d("swir1 nir", lambda xp, b, p: nd(b["swir1"], b["nir"]), low=-0.5, high=0.4, style="urban"),
    "UI": _d("swir2 nir", lambda xp, b, p: nd(b["swir2"], b["nir"]), low=-0.6, high=0.3, style="urban"),
    "IBI": _d("swir1 nir red green", _ibi, low=-0.4, high=0.3, style="urban"),
    "BUI": _d("swir1 nir red", lambda xp, b, p: nd(b["swir1"], b["nir"]) - _ndvi(xp, b, p), low=-1.0, high=0.6,
              style="urban"),
    # snow & ice
    "NDSI": _d("green swir1", lambda xp, b, p: nd(b["green"], b["swir1"]), low=-0.5, high=1.0, style="snow"),
    "NDGI": _d("green red", lambda xp, b, p: nd(b["green"], b["red"]), low=-0.2, high=0.2, style="snow"),
    "S3": _d("nir red swir1",
             lambda xp, b, p: b["nir"] * (b["red"] - b["swir1"]) / ((b["nir"] + b["red"]) * (b["nir"] + b["swir1"])),
             low=-0.3, high=0.5, style="snow"),
    # SAR
    "Backscatter_dB": _d("vv", lambda xp, b, p: b["vv"], low=-25.0, high=0.0, style="grey", unit="dB"),
    "VV_VH_ratio": _d("vv vh", lambda xp, b, p: b["vv"] - b["vh"], low=0.0, high=15.0, style="viridis", unit="dB"),
    "RVI_SAR": _d("vv vh", _rvi_sar, low=0.0, high=1.0, **_VEG),
    "RFDI": _d("hh hv", _rfdi, low=0.0, high=1.0, style="diverging"),
    "NDPI": _d("vv vh", _ndpi, low=-0.2, high=1.0, style="diverging"),
}

# Tasseled Cap coefficients for (Blue, Green, Red, NIR, SWIR1, SWIR2) reflectance.
TASSELED_CAP: dict[str, dict[str, tuple[float, ...]]] = {
    # Baig et al. (2014), Landsat 8 OLI
    "OLI": {
        "brightness": (0.3029, 0.2786, 0.4733, 0.5599, 0.5080, 0.1872),
        "greenness": (-0.2941, -0.2430, -0.5424, 0.7276, 0.0713, -0.1608),
        "wetness": (0.1511, 0.1973, 0.3283, 0.3407, -0.7117, -0.4559),
    },
    # Crist (1985), Landsat TM reflectance factors (also used for ETM+)
    "TM": {
        "brightness": (0.2043, 0.4158, 0.5524, 0.5741, 0.3124, 0.2303),
        "greenness": (-0.1603, -0.2819, -0.4934, 0.7940, -0.0002, -0.1446),
        "wetness": (0.0315, 0.2021, 0.3102, 0.1594, -0.6806, -0.6109),
    },
}
TASSELED_CAP_SENSOR = {"Landsat-8": "OLI", "Landsat-9": "OLI", "Landsat-5": "TM", "Landsat-7": "TM"}
TASSELED_CAP_ROLES = ("blue", "green", "red", "nir", "swir1", "swir2")
