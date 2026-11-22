from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from backend.business.catalog.downloader import ProgressCallback
from backend.dto.catalog_dto import CatalogRequestDTO, CatalogResultDTO, CatalogSourceDTO


class CatalogProvider(ABC):
    """A data provider the catalog can list and download from."""

    id: str

    @abstractmethod
    def source(self) -> CatalogSourceDTO:
        """The provider and the choices the UI offers for it."""

    @abstractmethod
    def download(self, request: CatalogRequestDTO, dest_dir: Path,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        """Download what ``request`` asks for into ``dest_dir`` (a fresh folder) and describe the result."""


def first_shapefile(paths: list[Path]) -> Optional[Path]:
    """The .shp among downloaded files to open first (prefer a non-empty one)."""
    shps = [p for p in paths if p.suffix.lower() == ".shp"]
    shps.sort(key=lambda p: (p.stat().st_size if p.exists() else 0), reverse=True)
    return shps[0] if shps else None


def first_raster(paths: list[Path]) -> Optional[Path]:
    """The raster to open first: a GeoTIFF, or a GDAL .vrt / DIVA .grd, largest first."""
    order = {".tif": 0, ".tiff": 0, ".vrt": 1, ".grd": 2}
    rasters = [p for p in paths if p.suffix.lower() in order]
    rasters.sort(key=lambda p: (order[p.suffix.lower()], -(p.stat().st_size if p.exists() else 0)))
    return rasters[0] if rasters else None
