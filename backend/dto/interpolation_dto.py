"""DTOs for IDW interpolation: the sample points, the parameters and the surface produced."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.dto.map_dto import LegendDTO


@dataclass(frozen=True)
class SamplePointDTO:
    """One measured point: its location (WGS84) and the value being interpolated."""

    lon: float
    lat: float
    value: float


@dataclass(frozen=True)
class IDWParamsDTO:
    """Inverse-distance-weighting parameters, as ArcGIS's IDW tool exposes them."""

    power: float = 2.0          # distance exponent: higher = more local influence
    neighbours: int = 12        # nearest points used per cell; 0 = every point
    radius: float = 0.0         # search radius in degrees; 0 = no limit
    resolution: int = 400       # longest side of the output grid, in cells
    # An area to interpolate over (e.g. the cities the user selected): polygons as tuples of
    # rings of (lon, lat), the first ring outer, the rest holes. With ``clip_to_boundary`` the
    # surface stops sharply at its edge; without, it only widens the surface to cover it.
    boundary: tuple = ()
    clip_to_boundary: bool = True


@dataclass(frozen=True)
class IDWResultDTO:
    """An interpolated surface drawn and ready to show (and to save as a GeoTIFF)."""

    values: object                              # numpy float32 (height, width); NaN where nothing was estimated
    rgba: object                                # numpy uint8 (height, width, 4); unestimated cells are transparent
    legend: LegendDTO
    width: int
    height: int
    bounds: tuple[float, float, float, float]   # minlon, minlat, maxlon, maxlat (WGS84)
    cell_size: tuple[float, float]              # (x, y) in degrees
    crs: str                                    # always "EPSG:4326"
    point_count: int
    field: str                                  # the attribute interpolated
    params: IDWParamsDTO
    stats: dict                                 # min, max, mean of the estimated surface
    notes: list[str] = field(default_factory=list)
