"""Write a GeoJSON FeatureCollection (e.g. from Earth Engine ``getInfo``) to an ESRI shapefile.

A shapefile holds one geometry type, so the first feature's type decides the layer's type and
features of a different type are skipped. Attribute names are shortened to the 10-character .dbf
limit and de-duplicated; a ``.prj`` declaring WGS84 is written alongside (GeoJSON is lon/lat).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import shapefile  # pyshp

from backend.exceptions import CatalogError

WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
)

_SHAPE_TYPE = {
    "Point": shapefile.POINT, "MultiPoint": shapefile.MULTIPOINT,
    "LineString": shapefile.POLYLINE, "MultiLineString": shapefile.POLYLINE,
    "Polygon": shapefile.POLYGON, "MultiPolygon": shapefile.POLYGON,
}
_POINT_LIKE = {"Point", "MultiPoint"}
_LINE_LIKE = {"LineString", "MultiLineString"}
_POLYGON_LIKE = {"Polygon", "MultiPolygon"}


def write_geojson(feature_collection: dict, out_path: str) -> list[str]:
    """Write ``feature_collection`` to ``out_path`` (a .shp). Returns every file written."""
    features = [f for f in (feature_collection or {}).get("features", []) if _geometry(f) is not None]
    if not features:
        raise CatalogError("The dataset has no features for this area.")

    target = Path(out_path)
    if target.suffix.lower() != ".shp":
        target = target.with_suffix(".shp")
    target.parent.mkdir(parents=True, exist_ok=True)

    first_type = _geometry(features[0])["type"]
    shape_type = _SHAPE_TYPE.get(first_type)
    if shape_type is None:
        raise CatalogError(f"Unsupported geometry type: {first_type}.")
    family = _family(first_type)

    originals = _originals(features)
    fields = _plan_fields(features, originals)  # one (name, type, size, decimal) per original, in order
    writer = shapefile.Writer(str(target), shapeType=shape_type)
    for _original, name, ftype, size, decimal in fields:
        writer.field(name, ftype, size, decimal)

    written = 0
    for feature in features:
        geometry = _geometry(feature)
        if _family(geometry["type"]) != family:
            continue  # a shapefile holds one geometry family; skip the odd ones out
        if not _write_geometry(writer, geometry):
            continue
        properties = feature.get("properties") or {}
        writer.record(*[_value(properties.get(original), ftype) for original, _name, ftype, _s, _d in fields])
        written += 1
    writer.close()
    if written == 0:
        raise CatalogError("No features of a single geometry type could be written.")

    target.with_suffix(".prj").write_text(WGS84_WKT, encoding="utf-8")
    return [str(target.with_suffix(ext)) for ext in (".shp", ".dbf", ".shx", ".prj")
            if target.with_suffix(ext).is_file()]


# ------------------------------------------------------------- helpers
def _geometry(feature: dict) -> dict | None:
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    if isinstance(geometry, dict) and geometry.get("type") in _SHAPE_TYPE and geometry.get("coordinates"):
        return geometry
    return None


def _family(geometry_type: str) -> str:
    if geometry_type in _POINT_LIKE:
        return "point"
    if geometry_type in _LINE_LIKE:
        return "line"
    return "polygon"


def _originals(features: list[dict]) -> list[str]:
    keys: list[str] = []
    for feature in features:
        for key in (feature.get("properties") or {}):
            if key not in keys:
                keys.append(key)
    return keys


def _plan_fields(features: list[dict], originals: list[str]) -> list[tuple[str, str, str, int, int]]:
    """One (original name, dbf name, dbf type, size, decimal) per attribute, in order.

    dbf names are truncated to 10 characters and de-duplicated.
    """
    planned: list[tuple[str, str, str, int, int]] = []
    used: set[str] = set()
    for original in originals:
        values = [f.get("properties", {}).get(original) for f in features]
        ftype, size, decimal = _infer_type(values)
        name = _unique(original[:10], used)
        used.add(name)
        planned.append((original, name, ftype, size, decimal))
    return planned


def _infer_type(values: list[Any]) -> tuple[str, int, int]:
    present = [v for v in values if v is not None]
    if present and all(isinstance(v, bool) for v in present):
        return "L", 1, 0
    if present and all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return "N", 18, 0
    if present and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return "F", 19, 8
    size = max((len(str(v)) for v in present), default=1)
    return "C", min(254, max(1, size)), 0


def _value(value: Any, ftype: str) -> Any:
    if value is None:
        return "" if ftype == "C" else None
    if ftype == "C":
        return str(value)[:254]
    return value


def _unique(name: str, used: set[str]) -> str:
    name = name or "field"
    if name not in used:
        return name
    for i in range(1, 1000):
        candidate = f"{name[:10 - len(str(i))]}{i}"
        if candidate not in used:
            return candidate
    return name


def _write_geometry(writer: Any, geometry: dict) -> bool:
    gtype, coords = geometry["type"], geometry["coordinates"]
    try:
        if gtype == "Point":
            writer.point(coords[0], coords[1])
        elif gtype == "MultiPoint":
            writer.multipoint([[c[0], c[1]] for c in coords])
        elif gtype == "LineString":
            writer.line([[[c[0], c[1]] for c in coords]])
        elif gtype == "MultiLineString":
            writer.line([[[c[0], c[1]] for c in line] for line in coords])
        elif gtype == "Polygon":
            writer.poly([[[c[0], c[1]] for c in ring] for ring in coords])
        elif gtype == "MultiPolygon":
            rings = [[[c[0], c[1]] for c in ring] for polygon in coords for ring in polygon]
            writer.poly(rings)
        else:
            return False
    except (IndexError, TypeError, ValueError):
        return False
    return True
