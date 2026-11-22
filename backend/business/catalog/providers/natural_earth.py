"""Natural Earth: free global vector layers at three scales, from a stable CDN.

URLs look like ``https://naciscdn.org/naturalearth/<scale>/<theme>/ne_<scale>_<name>.zip``.
Not every layer exists at every scale; an unavailable combination comes back as HTTP 404,
which the downloader reports to the user.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.business.catalog.downloader import ProgressCallback, download_and_extract
from backend.business.catalog.providers.base import CatalogProvider, first_shapefile
from backend.dto.catalog_dto import (
    OPEN_IN_VECTOR,
    CatalogDatasetDTO,
    CatalogOptionDTO,
    CatalogRequestDTO,
    CatalogResultDTO,
    CatalogSourceDTO,
)
from backend.exceptions import CatalogError

BASE_URL = "https://naciscdn.org/naturalearth"

# dataset id -> (label, theme, Natural Earth layer name, description)
_LAYERS: dict[str, tuple[str, str, str, str]] = {
    "countries": ("Countries", "cultural", "admin_0_countries", "National boundaries (polygons)."),
    "states": ("States / provinces", "cultural", "admin_1_states_provinces", "First-level admin boundaries."),
    "populated_places": ("Populated places", "cultural", "populated_places", "Cities and towns (points)."),
    "urban_areas": ("Urban areas", "cultural", "urban_areas", "Built-up urban extents (polygons)."),
    "roads": ("Roads", "cultural", "roads", "Major roads (lines; 10m only)."),
    "rivers": ("Rivers & lake lines", "physical", "rivers_lake_centerlines", "River centre lines."),
    "lakes": ("Lakes", "physical", "lakes", "Lake and reservoir polygons."),
    "coastline": ("Coastline", "physical", "coastline", "World coastline (lines)."),
    "land": ("Land", "physical", "land", "Land polygons."),
}
_SCALES = ("10m", "50m", "110m")


class NaturalEarthProvider(CatalogProvider):
    id = "natural_earth"

    def source(self) -> CatalogSourceDTO:
        datasets = tuple(
            CatalogDatasetDTO(key, label, kind="vector", open_in=OPEN_IN_VECTOR, description=desc)
            for key, (label, _theme, _name, desc) in _LAYERS.items()
        )
        scales = (CatalogOptionDTO("10m", "1:10m (detailed)"), CatalogOptionDTO("50m", "1:50m (medium)"),
                  CatalogOptionDTO("110m", "1:110m (coarse)"))
        return CatalogSourceDTO(
            id=self.id, name="Natural Earth", kind="http",
            description="Free global basemap vectors (boundaries, places, rivers, lakes) at three scales.",
            datasets=datasets, scales=scales, attribution="Natural Earth (public domain)",
        )

    def download(self, request: CatalogRequestDTO, dest_dir: Path,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        layer = _LAYERS.get(request.dataset_id)
        if layer is None:
            raise CatalogError(f"Unknown Natural Earth layer: {request.dataset_id!r}.")
        label, theme, name, _desc = layer
        scale = request.scale_id if request.scale_id in _SCALES else "110m"
        url = f"{BASE_URL}/{scale}/{theme}/ne_{scale}_{name}.zip"
        files = download_and_extract(url, dest_dir, on_progress=on_progress)
        shp = first_shapefile(files)
        if shp is None:
            raise CatalogError("The Natural Earth archive did not contain a shapefile.")
        return CatalogResultDTO(
            paths=[str(p) for p in files], primary_path=str(shp), kind="vector", open_in=OPEN_IN_VECTOR,
            name=f"Natural Earth · {label} ({scale})",
            notes=[f"Downloaded from {url}"],
        )
