"""Earth Engine vectors: administrative boundaries, water & watersheds, and protected areas.

A FeatureCollection is clipped to the chosen area of interest and fetched with ``getInfo`` (so
the result is capped to a few thousand features), then written to a shapefile. A large area or a
dense dataset may hit Earth Engine's payload limit — pick a smaller area or a coarser dataset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from backend.business.catalog.downloader import ProgressCallback
from backend.business.catalog.geojson_to_shapefile import write_geojson
from backend.business.catalog.providers.base import CatalogProvider
from backend.dto.catalog_dto import (
    OPEN_IN_VECTOR,
    CatalogDatasetDTO,
    CatalogRequestDTO,
    CatalogResultDTO,
    CatalogSourceDTO,
)
from backend.exceptions import CatalogError

# Callable that returns a FeatureCollection as GeoJSON: (asset_id, aoi_geojson, limit) -> dict.
FeatureFetcher = Callable[[str, str, int], dict]

# dataset id -> (label, GEE asset, description)
_ASSETS: dict[str, tuple[str, str, str]] = {
    "admin0": ("Admin boundaries — countries", "FAO/GAUL/2015/level0", "FAO GAUL national boundaries."),
    "admin1": ("Admin boundaries — level 1", "FAO/GAUL/2015/level1", "FAO GAUL first-level boundaries."),
    "admin2": ("Admin boundaries — level 2", "FAO/GAUL/2015/level2", "FAO GAUL second-level boundaries."),
    "watersheds": ("Watersheds (HydroSHEDS)", "WWF/HydroSHEDS/v1/Basins/hybas_6",
                   "HydroBASINS level-6 drainage basins."),
    "rivers": ("Rivers (free-flowing)", "WWF/HydroSHEDS/v1/FreeFlowingRivers",
               "HydroSHEDS free-flowing river network."),
    "protected": ("Protected areas (WDPA)", "WCMC/WDPA/current/polygons",
                  "World Database on Protected Areas polygons."),
}


class EarthEngineProvider(CatalogProvider):
    id = "earth_engine"

    def __init__(self, fetch_features: FeatureFetcher):
        self._fetch_features = fetch_features

    def source(self) -> CatalogSourceDTO:
        datasets = tuple(
            CatalogDatasetDTO(key, label, kind="vector", open_in=OPEN_IN_VECTOR, description=desc, needs_area=True)
            for key, (label, _asset, desc) in _ASSETS.items()
        )
        return CatalogSourceDTO(
            id=self.id, name="Earth Engine vectors", kind="earth_engine",
            description="Administrative boundaries, watersheds and protected areas from Google Earth Engine, "
                        "clipped to an area of interest.",
            datasets=datasets, needs_area=True, attribution="Google Earth Engine data catalog",
        )

    def download(self, request: CatalogRequestDTO, dest_dir: Path,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        asset = _ASSETS.get(request.dataset_id)
        if asset is None:
            raise CatalogError(f"Unknown Earth Engine dataset: {request.dataset_id!r}.")
        label, asset_id, _desc = asset
        if not request.aoi_geojson:
            raise CatalogError("Choose an area of interest first (search for a place) — Earth Engine clips to it.")
        if on_progress is not None:
            on_progress(0, 0)  # indeterminate: one getInfo call
        geojson = self._fetch_features(asset_id, request.aoi_geojson, request.max_features)
        count = len(geojson.get("features", []))
        stem = _safe_stem(f"{request.dataset_id}_{request.area_name or 'aoi'}")
        files = write_geojson(geojson, str(dest_dir / f"{stem}.shp"))
        notes = [f"{count} features from {asset_id}" + (" (capped)" if count >= request.max_features else "")]
        if count >= request.max_features:
            notes.append("The result was capped; use a smaller area for the full dataset.")
        return CatalogResultDTO(
            paths=files, primary_path=files[0], kind="vector", open_in=OPEN_IN_VECTOR,
            name=f"Earth Engine · {label}" + (f" · {request.area_name}" if request.area_name else ""),
            notes=notes,
        )


def _safe_stem(text: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_" else "_" for c in text)
    return (keep.strip("_") or "earth_engine")[:40]
