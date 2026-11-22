"""DTOs for the Digital Elevation Model (terrain) page: a DEM's details and its derived surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.dto.map_dto import LegendDTO


@dataclass(frozen=True)
class TerrainInfoDTO:
    """What a DEM GeoTIFF holds (its first band is taken as elevation)."""

    path: str
    name: str
    width: int
    height: int
    crs: str
    bounds: tuple[float, float, float, float]   # west, south, east, north (in the file's CRS)
    nodata: float | None
    cell_size: tuple[float, float]              # (x, y) pixel size in the CRS's units
    is_geographic: bool                         # True when the CRS is in degrees (cell size is then in degrees)
    unit: str                                   # "m" or "ft" etc. for the elevation values
    min_elevation: float
    max_elevation: float
    mean_elevation: float
    size_bytes: int


@dataclass(frozen=True)
class TerrainProductDTO:
    """A derived terrain surface drawn and ready to show (hillshade, slope, aspect, ...)."""

    key: str                                    # "elevation" / "hillshade" / "slope" / "aspect" / "contours"
    label: str
    rgba: object                                # numpy uint8 (height, width, 4); no-data is transparent
    legend: LegendDTO
    width: int
    height: int
    scale: float                                # DEM pixels per preview pixel (>= 1)
    values: object = None                       # numpy float32 (height, width) of the surface's own values; NaN = no-data
    unit: str = ""                              # the values' unit, e.g. "°" for slope, "m" for elevation
    notes: list[str] = field(default_factory=list)
