"""DTOs for the Data Catalog: the providers, their datasets, a download request and its result."""

from __future__ import annotations

from dataclasses import dataclass, field

# Where a downloaded dataset is meant to be opened in the app.
OPEN_IN_VECTOR = "vector"   # a shapefile -> Vector Maps
OPEN_IN_DEM = "dem"         # an elevation raster -> Digital Elevation Model
OPEN_IN_IDW = "idw"         # a point layer of measurements -> IDW Interpolation


@dataclass(frozen=True)
class CatalogOptionDTO:
    """One choice in a source's selector (a Natural Earth scale, a Geofabrik region, ...)."""

    id: str
    label: str


@dataclass(frozen=True)
class CatalogDatasetDTO:
    """One dataset a source can download."""

    id: str
    label: str
    kind: str = "vector"            # "vector" | "raster" | "points"
    open_in: str = OPEN_IN_VECTOR
    description: str = ""
    needs_area: bool = False        # True for Earth Engine: it is clipped to an area of interest


@dataclass(frozen=True)
class CatalogSourceDTO:
    """A data provider and what the UI needs to let the user pick from it."""

    id: str                         # "earth_engine" | "natural_earth" | "geofabrik" | "hdx"
    name: str
    kind: str                       # "earth_engine" | "http" | "search"
    description: str
    datasets: tuple[CatalogDatasetDTO, ...] = ()
    scales: tuple[CatalogOptionDTO, ...] = ()     # Natural Earth scales
    regions: tuple[CatalogOptionDTO, ...] = ()    # Geofabrik regions
    supports_search: bool = False                 # HDX: a free-text search box
    needs_area: bool = False                      # Earth Engine: an area of interest is required
    attribution: str = ""                         # the provider's name / licence note to show


@dataclass(frozen=True)
class CatalogRequestDTO:
    """What the user chose to download."""

    source_id: str
    dataset_id: str = ""
    scale_id: str = ""
    region_id: str = ""
    query: str = ""                 # HDX search text
    aoi_geojson: str = ""           # Earth Engine: the clip geometry (GeoJSON)
    area_name: str = ""             # for naming the output and for notes
    max_features: int = 5000        # Earth Engine: cap getInfo payload


@dataclass
class CatalogResultDTO:
    """The outcome of a download: the files written and where to open them."""

    paths: list[str]                # every file written (a shapefile is one .shp plus its sidecars)
    primary_path: str               # the file the app should open
    kind: str                       # "vector" | "raster" | "points"
    open_in: str                    # OPEN_IN_VECTOR / OPEN_IN_DEM / OPEN_IN_IDW
    name: str
    notes: list[str] = field(default_factory=list)
