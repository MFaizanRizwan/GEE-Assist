"""Geofabrik: OpenStreetMap extracts by region as zipped shapefiles.

URLs look like ``https://download.geofabrik.de/<path>-latest-free.shp.zip``. Each archive holds
several layers (roads, buildings, water, points of interest, ...); the largest shapefile is
opened first and the rest are left in the folder for the user to open from Vector Maps.
These files can be large — a country is often hundreds of megabytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.business.catalog.downloader import ProgressCallback, download_and_extract
from backend.business.catalog.providers.base import CatalogProvider, first_shapefile
from backend.dto.catalog_dto import (
    OPEN_IN_VECTOR,
    CatalogOptionDTO,
    CatalogRequestDTO,
    CatalogResultDTO,
    CatalogSourceDTO,
)
from backend.exceptions import CatalogError

BASE_URL = "https://download.geofabrik.de"

# region id -> (label, Geofabrik path). A curated subset; the path maps straight to the URL.
_REGIONS: dict[str, tuple[str, str]] = {
    "pakistan": ("Pakistan", "asia/pakistan"),
    "india": ("India", "asia/india"),
    "bangladesh": ("Bangladesh", "asia/bangladesh"),
    "china": ("China", "asia/china"),
    "japan": ("Japan", "asia/japan"),
    "indonesia": ("Indonesia", "asia/indonesia"),
    "germany": ("Germany", "europe/germany"),
    "france": ("France", "europe/france"),
    "great-britain": ("Great Britain", "europe/great-britain"),
    "italy": ("Italy", "europe/italy"),
    "spain": ("Spain", "europe/spain"),
    "egypt": ("Egypt", "africa/egypt"),
    "nigeria": ("Nigeria", "africa/nigeria"),
    "south-africa": ("South Africa", "africa/south-africa"),
    "kenya": ("Kenya", "africa/kenya"),
    "brazil": ("Brazil", "south-america/brazil"),
    "mexico": ("Mexico", "north-america/mexico"),
    "australia": ("Australia", "australia-oceania/australia"),
}


class GeofabrikProvider(CatalogProvider):
    id = "geofabrik"

    def source(self) -> CatalogSourceDTO:
        regions = tuple(CatalogOptionDTO(key, label) for key, (label, _path) in sorted(
            _REGIONS.items(), key=lambda item: item[1][0]))
        return CatalogSourceDTO(
            id=self.id, name="Geofabrik (OpenStreetMap)", kind="http",
            description="OpenStreetMap roads, buildings, water and places by region, as shapefiles. "
                        "Files can be large (hundreds of MB for a country).",
            regions=regions, attribution="© OpenStreetMap contributors (ODbL), via Geofabrik",
        )

    def download(self, request: CatalogRequestDTO, dest_dir: Path,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        region = _REGIONS.get(request.region_id)
        if region is None:
            raise CatalogError(f"Unknown Geofabrik region: {request.region_id!r}.")
        label, path = region
        url = f"{BASE_URL}/{path}-latest-free.shp.zip"
        files = download_and_extract(url, dest_dir, on_progress=on_progress)
        shp = first_shapefile(files)
        if shp is None:
            raise CatalogError("The Geofabrik archive did not contain a shapefile.")
        shp_count = sum(1 for p in files if p.suffix.lower() == ".shp")
        return CatalogResultDTO(
            paths=[str(p) for p in files], primary_path=str(shp), kind="vector", open_in=OPEN_IN_VECTOR,
            name=f"OSM · {label}",
            notes=[f"{shp_count} layers extracted to {dest_dir}. Opening the largest; open the rest from Vector Maps."],
        )
