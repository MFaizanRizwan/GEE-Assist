from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from backend.dto.catalog_dto import CatalogRequestDTO, CatalogResultDTO, CatalogSourceDTO

# Download progress: (bytes received, total bytes; total 0 = unknown).
ProgressCallback = Callable[[int, int], None]


class ICatalogService(ABC):
    """Class diagram: «interface» ICatalogService. Lists data providers and downloads from them."""

    @abstractmethod
    def list_sources(self) -> list[CatalogSourceDTO]:
        """Every provider and the choices it offers."""

    @abstractmethod
    def download(self, request: CatalogRequestDTO, dest_dir: str,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        """Download what ``request`` asks for into a fresh folder under ``dest_dir``."""
