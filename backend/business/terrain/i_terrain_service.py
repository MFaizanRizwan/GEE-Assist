from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.dto.terrain_dto import TerrainInfoDTO, TerrainProductDTO

# The surfaces that can be derived from a DEM (ArcGIS "Surface" tools).
PRODUCTS: tuple[tuple[str, str], ...] = (
    ("elevation", "Elevation (shaded relief)"),
    ("hillshade", "Hillshade"),
    ("slope", "Slope"),
    ("aspect", "Aspect"),
    ("contours", "Contours"),
)


class ITerrainService(ABC):
    """Class diagram: «interface» ITerrainService. Reads a DEM and derives terrain surfaces."""

    @abstractmethod
    def describe(self, path: str) -> TerrainInfoDTO:
        """Read a DEM GeoTIFF's details (its first band is the elevation). ``TerrainError`` if it cannot be read."""

    @abstractmethod
    def render(self, info: TerrainInfoDTO, product: str, params: dict[str, Any] | None = None,
               max_size: int = 1600) -> TerrainProductDTO:
        """Draw one derived surface (``elevation`` / ``hillshade`` / ``slope`` / ``aspect`` / ``contours``)."""

    @abstractmethod
    def save_product(self, info: TerrainInfoDTO, product: str, path: str,
                     params: dict[str, Any] | None = None) -> str:
        """Compute a surface at the DEM's full resolution and write it as a GeoTIFF; returns its path."""
