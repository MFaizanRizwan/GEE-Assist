"""DIVA-GIS: free country-level GIS data (now hosted at geodata.ucdavis.edu/diva).

URLs look like ``https://geodata.ucdavis.edu/diva/<theme>/<ISO3>_<theme>.zip``. Themes used:
administrative boundaries, roads and water (shapefiles) and elevation (a DIVA ``.grd/.gri/.vrt``
raster, converted here to a GeoTIFF for the DEM page). The data is older (SRTM-era) but handy
for whole-country coverage in one download.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.business.catalog.countries import options
from backend.business.catalog.downloader import ProgressCallback, download_and_extract
from backend.business.catalog.providers.base import CatalogProvider, first_raster, first_shapefile
from backend.dto.catalog_dto import (
    OPEN_IN_DEM,
    OPEN_IN_VECTOR,
    CatalogDatasetDTO,
    CatalogRequestDTO,
    CatalogResultDTO,
    CatalogSourceDTO,
)
from backend.exceptions import CatalogError

BASE_URL = "https://geodata.ucdavis.edu/diva"

# dataset id -> (label, DIVA theme, kind, open_in, description)
_THEMES: dict[str, tuple[str, str, str, str, str]] = {
    "admin": ("Administrative boundaries", "adm", "vector", OPEN_IN_VECTOR, "Country / province / district outlines."),
    "roads": ("Roads", "rds", "vector", OPEN_IN_VECTOR, "Road network (lines)."),
    "water": ("Rivers & water", "wat", "vector", OPEN_IN_VECTOR, "Rivers, canals and water bodies."),
    "elevation": ("Elevation (DEM)", "msk_alt", "raster", OPEN_IN_DEM,
                  "SRTM-derived elevation raster — opens on the DEM page."),
}


class DivaGisProvider(CatalogProvider):
    id = "diva_gis"

    def source(self) -> CatalogSourceDTO:
        datasets = tuple(
            CatalogDatasetDTO(key, label, kind=kind, open_in=open_in, description=desc)
            for key, (label, _theme, kind, open_in, desc) in _THEMES.items()
        )
        return CatalogSourceDTO(
            id=self.id, name="DIVA-GIS (by country)", kind="http",
            description="Free country-level boundaries, roads, rivers and an elevation DEM. Pick a country.",
            datasets=datasets, regions=options("iso3"), attribution="DIVA-GIS / UC Davis",
        )

    def download(self, request: CatalogRequestDTO, dest_dir: Path,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        theme = _THEMES.get(request.dataset_id)
        if theme is None:
            raise CatalogError(f"Unknown DIVA-GIS dataset: {request.dataset_id!r}.")
        if not request.region_id:
            raise CatalogError("Choose a country first.")
        label, code, kind, open_in, _desc = theme
        url = f"{BASE_URL}/{code}/{request.region_id}_{code}.zip"
        files = download_and_extract(url, dest_dir, on_progress=on_progress)

        if kind == "raster":
            source = first_raster(files)
            if source is None:
                raise CatalogError("The DIVA-GIS archive did not contain an elevation raster.")
            primary = _to_geotiff(source)
            return CatalogResultDTO(
                paths=[str(p) for p in files] + [primary], primary_path=primary, kind="raster", open_in=open_in,
                name=f"DIVA-GIS · {label} · {request.region_id}", notes=["Converted the DIVA raster to GeoTIFF."])
        shp = first_shapefile([Path(p) for p in files])
        if shp is None:
            raise CatalogError("The DIVA-GIS archive did not contain a shapefile.")
        return CatalogResultDTO(
            paths=[str(p) for p in files], primary_path=str(shp), kind="vector", open_in=open_in,
            name=f"DIVA-GIS · {label} · {request.region_id}",
            notes=[f"Extracted to {dest_dir}; open other layers from Vector Maps if there are several."])


def _to_geotiff(source: Path) -> str:
    """Convert a DIVA ``.vrt`` / ``.grd`` elevation raster to a GeoTIFF beside it."""
    import rasterio

    target = source.with_suffix(".tif")
    try:
        with rasterio.open(str(source)) as src:
            profile = src.profile
            data = src.read()
        profile.update(driver="GTiff", count=data.shape[0], compress="deflate")
        with rasterio.open(str(target), "w", **profile) as dst:
            dst.write(data)
    except Exception as exc:  # fall back to the raw raster, which rasterio can still open
        raise CatalogError(f"The elevation raster could not be converted to GeoTIFF: {exc}") from exc
    return str(target)
