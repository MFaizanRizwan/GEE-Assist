"""Reads ESRI shapefiles for the Vector Maps page.

A shapefile is a set of files sharing one name: ``.shp`` (geometry), ``.dbf`` (attributes),
``.shx`` (index) and, usually, ``.prj`` (the coordinate system). The geometry is read with
``pyshp`` and reprojected to WGS84 (longitude / latitude) with rasterio's transformer, so the
UI draws everything on one planar canvas regardless of the file's own projection.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Optional

import shapefile  # pyshp

from backend.business.vector.i_vector_service import IVectorService
from backend.dto.vector_dto import (
    MULTIPOINT,
    POINT,
    POLYGON,
    POLYLINE,
    VectorFeatureDTO,
    VectorFieldDTO,
    VectorLayerDTO,
)
from backend.exceptions import VectorError

logger = logging.getLogger(__name__)

# ESRI shape type number -> our normalised geometry kind (the Z and M variants collapse in).
_KIND: dict[int, str] = {
    1: POINT, 11: POINT, 21: POINT,
    3: POLYLINE, 13: POLYLINE, 23: POLYLINE,
    5: POLYGON, 15: POLYGON, 25: POLYGON, 31: POLYGON,  # 31 = MultiPatch, drawn as polygons
    8: MULTIPOINT, 18: MULTIPOINT, 28: MULTIPOINT,
}

# .dbf field type letter -> a friendly name.
_FIELD_TYPE = {"C": "text", "N": "number", "F": "number", "O": "number", "D": "date", "L": "logical"}


class VectorService(IVectorService):
    def __init__(self, max_features: int = 200_000) -> None:
        # A guard against pathologically large files locking up the UI; normal shapefiles are far smaller.
        self._max_features = max_features

    def load_shapefile(self, path: str) -> VectorLayerDTO:
        file = Path(path)
        if file.suffix.lower() != ".shp":
            raise VectorError("Choose a shapefile (its .shp file).")
        if not file.is_file():
            raise VectorError(f"The shapefile is not there: {file}")
        if not file.with_suffix(".dbf").is_file():
            raise VectorError("The shapefile's .dbf (attributes) is missing; the .shp needs its .dbf and .shx.")

        try:
            reader = shapefile.Reader(str(file))
        except shapefile.ShapefileException as exc:
            raise VectorError(f"The shapefile could not be read: {exc}") from exc
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise VectorError(f"The shapefile could not be read: {exc}") from exc

        try:
            with reader:
                return self._build(file, reader)
        except shapefile.ShapefileException as exc:
            raise VectorError(f"The shapefile could not be read: {exc}") from exc

    # ------------------------------------------------------------- building
    def _build(self, file: Path, reader: "shapefile.Reader") -> VectorLayerDTO:
        field_names = [f[0] for f in reader.fields[1:]]  # the first field is the deletion flag
        fields = tuple(VectorFieldDTO(f[0], _FIELD_TYPE.get(str(f[1]).upper(), "text")) for f in reader.fields[1:])
        src_crs, crs_label = _read_crs(file)

        raw: list[tuple[str, list[list[tuple[float, float]]], dict[str, Any]]] = []
        xs: list[float] = []
        ys: list[float] = []
        for record in reader.iterShapeRecords():
            kind = _KIND.get(record.shape.shapeType)
            if kind is None:  # NULL geometry, or an unsupported type
                continue
            parts = _split_parts(record.shape, kind)
            if not parts:
                continue
            raw.append((kind, parts, _record_dict(record.record, field_names)))
            for part in parts:
                for x, y in part:
                    xs.append(x)
                    ys.append(y)
            if len(raw) > self._max_features:
                raise VectorError(f"This shapefile has more than {self._max_features:,} features, too many to show.")

        if not raw:
            raise VectorError("The shapefile has no features to show.")

        if src_crs is not None and not _is_wgs84(src_crs) and xs:
            xs, ys = _reproject(src_crs, xs, ys)

        features: list[VectorFeatureDTO] = []
        layer_bounds = [math.inf, math.inf, -math.inf, -math.inf]
        cursor = 0
        for kind, parts, attrs in raw:
            new_parts: list[tuple[tuple[float, float], ...]] = []
            feature_bounds = [math.inf, math.inf, -math.inf, -math.inf]
            for part in parts:
                ring: list[tuple[float, float]] = []
                for _ in part:
                    lon, lat = xs[cursor], ys[cursor]
                    cursor += 1
                    ring.append((lon, lat))
                    _extend(feature_bounds, lon, lat)
                    _extend(layer_bounds, lon, lat)
                new_parts.append(tuple(ring))
            features.append(VectorFeatureDTO(kind, tuple(new_parts), attrs, _as_bounds(feature_bounds)))

        layer_kind = _KIND.get(reader.shapeType) or features[0].kind
        return VectorLayerDTO(
            path=str(file),
            name=file.stem,
            kind=layer_kind,
            crs=crs_label,
            feature_count=len(features),
            fields=fields,
            features=tuple(features),
            bounds=_as_bounds(layer_bounds),
        )


# ------------------------------------------------------------- helpers
def _split_parts(shape: Any, kind: str) -> list[list[tuple[float, float]]]:
    """The geometry's rings/paths as lists of (x, y), ignoring any Z/M values."""
    points = [(float(p[0]), float(p[1])) for p in shape.points if len(p) >= 2]
    if not points:
        return []
    if kind in (POINT, MULTIPOINT):
        return [points]
    starts = list(shape.parts) or [0]
    starts.append(len(points))
    parts = [points[starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]
    return [part for part in parts if part]


def _record_dict(record: Any, field_names: list[str]) -> dict[str, Any]:
    values = list(record)
    attrs: dict[str, Any] = {}
    for name, value in zip(field_names, values):
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", "replace").strip()
            except Exception:  # pragma: no cover - decode is very forgiving
                value = str(value)
        attrs[name] = value
    return attrs


def _read_crs(file: Path) -> tuple[Optional[object], str]:
    """The source coordinate system from the ``.prj`` sidecar: (CRS or None, a label to show)."""
    prj = file.with_suffix(".prj")
    if not prj.is_file():
        return None, "unknown (assumed WGS84)"
    try:
        from rasterio.crs import CRS

        crs = CRS.from_wkt(prj.read_text(encoding="utf-8", errors="replace").strip())
    except Exception:
        logger.info("Could not read the .prj of %s; assuming WGS84", file.name, exc_info=True)
        return None, "unknown (assumed WGS84)"
    epsg = None
    try:
        epsg = crs.to_epsg()
    except Exception:  # pragma: no cover - defensive
        epsg = None
    return crs, (f"EPSG:{epsg}" if epsg else "custom (from .prj)")


def _is_wgs84(crs: Any) -> bool:
    try:
        return crs.to_epsg() == 4326
    except Exception:  # pragma: no cover - defensive
        return False


def _reproject(src_crs: Any, xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    try:
        from rasterio.crs import CRS
        from rasterio.warp import transform

        out_x, out_y = transform(src_crs, CRS.from_epsg(4326), xs, ys)
        return list(out_x), list(out_y)
    except Exception as exc:
        raise VectorError(f"The shapefile's coordinates could not be reprojected to latitude/longitude: {exc}") from exc


def _extend(bounds: list[float], lon: float, lat: float) -> None:
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return
    bounds[0] = min(bounds[0], lon)
    bounds[1] = min(bounds[1], lat)
    bounds[2] = max(bounds[2], lon)
    bounds[3] = max(bounds[3], lat)


def _as_bounds(bounds: list[float]) -> tuple[float, float, float, float]:
    if not math.isfinite(bounds[0]):
        return (0.0, 0.0, 0.0, 0.0)
    return (bounds[0], bounds[1], bounds[2], bounds[3])
