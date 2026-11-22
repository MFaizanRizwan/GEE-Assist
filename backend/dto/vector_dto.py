"""DTOs for vector maps (ESRI shapefiles): a layer's geometry and attributes, for display.

Everything here is already reprojected to WGS84 (longitude, latitude in degrees), so the
UI can draw it on one planar canvas without knowing about projections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Geometry kinds, normalised from the many ESRI shape types (Z / M variants collapse into these).
POINT = "point"
MULTIPOINT = "multipoint"
POLYLINE = "polyline"
POLYGON = "polygon"

# A single ring / path: the points of one part of a geometry.
Ring = tuple[tuple[float, float], ...]
Bounds = tuple[float, float, float, float]  # minlon, minlat, maxlon, maxlat (WGS84)


@dataclass(frozen=True)
class VectorFieldDTO:
    """One attribute column of a shapefile (from its .dbf)."""

    name: str
    type: str  # "text", "number", "date" or "logical"


@dataclass(frozen=True)
class VectorFeatureDTO:
    """One feature: its geometry (WGS84) and attribute values.

    ``parts`` is one or more rings/paths. A point/multipoint feature keeps its points in a
    single part; a polyline keeps one part per path; a polygon's first ring is the outer
    boundary and any further rings are holes (drawn with the even-odd rule).
    """

    kind: str  # POINT / MULTIPOINT / POLYLINE / POLYGON
    parts: tuple[Ring, ...]
    attributes: dict[str, Any]
    bounds: Bounds


@dataclass(frozen=True)
class VectorLayerDTO:
    """A whole shapefile loaded and reprojected, ready to show on the Vector Maps page."""

    path: str
    name: str  # file name without ".shp"
    kind: str  # the layer's geometry kind
    crs: str  # source CRS label, e.g. "EPSG:4326" or "unknown"
    feature_count: int
    fields: tuple[VectorFieldDTO, ...]
    features: tuple[VectorFeatureDTO, ...]
    bounds: Bounds  # the layer's extent in WGS84
