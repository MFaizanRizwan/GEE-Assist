from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from backend.dto.interpolation_dto import IDWParamsDTO, IDWResultDTO, SamplePointDTO


class IInterpolationService(ABC):
    """Class diagram: «interface» IInterpolationService. Interpolates scattered points into a raster surface."""

    @abstractmethod
    def interpolate_idw(self, points: Sequence[SamplePointDTO], field: str,
                        params: IDWParamsDTO | None = None) -> IDWResultDTO:
        """Inverse-distance-weighted surface from the sample points. ``InterpolationError`` if it cannot be built."""

    @abstractmethod
    def save_surface(self, result: IDWResultDTO, path: str) -> str:
        """Write an interpolated surface as a GeoTIFF (EPSG:4326); returns its path."""

    @abstractmethod
    def inspect_points_csv(self, path: str):
        """A CSV's columns, its numeric ones and the longitude / latitude columns guessed (CsvTableDTO)."""

    @abstractmethod
    def load_points_csv(self, path: str, lon_column: str = "", lat_column: str = ""):
        """A CSV's rows as a point layer (VectorLayerDTO, WGS84), for IDW."""
