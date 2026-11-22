from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.vector_dto import VectorLayerDTO


class IVectorService(ABC):
    """Class diagram: «interface» IVectorService. Reads vector maps (shapefiles) for display."""

    @abstractmethod
    def load_shapefile(self, path: str) -> VectorLayerDTO:
        """Read a ``.shp`` (with its ``.dbf`` / ``.shx`` / ``.prj``), reproject it to WGS84,
        and return every feature with its attributes. ``VectorError`` if it cannot be read."""
