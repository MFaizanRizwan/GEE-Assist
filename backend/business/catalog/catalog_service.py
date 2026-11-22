"""Lists data providers and downloads datasets from them into the user's folders.

Each download goes into its own fresh subfolder (a shapefile is several files; an OSM extract is
many), so downloads never overwrite one another. The provider does the actual fetching; this
service just routes the request and keeps folders tidy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

from backend.business.catalog.i_catalog_service import ICatalogService, ProgressCallback
from backend.business.catalog.providers.base import CatalogProvider
from backend.dto.catalog_dto import CatalogRequestDTO, CatalogResultDTO, CatalogSourceDTO
from backend.exceptions import CatalogError, GeeAssistError

logger = logging.getLogger(__name__)


class CatalogService(ICatalogService):
    def __init__(self, providers: Sequence[CatalogProvider]):
        self._providers: dict[str, CatalogProvider] = {provider.id: provider for provider in providers}

    def list_sources(self) -> list[CatalogSourceDTO]:
        return [provider.source() for provider in self._providers.values()]

    def download(self, request: CatalogRequestDTO, dest_dir: str,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        provider = self._providers.get(request.source_id)
        if provider is None:
            raise CatalogError(f"Unknown data source: {request.source_id!r}.")
        folder = _fresh_folder(Path(dest_dir), self._folder_name(request))
        try:
            return provider.download(request, folder, on_progress)
        except GeeAssistError:
            raise
        except Exception as exc:  # a provider bug or an unexpected network/parse error
            logger.exception("Catalog download failed for %s", request.source_id)
            raise CatalogError(f"The download could not be completed: {exc}") from exc

    def _folder_name(self, request: CatalogRequestDTO) -> str:
        parts = [request.source_id, request.dataset_id or request.region_id or request.query or "data"]
        if request.area_name:
            parts.append(request.area_name)
        stem = "_".join(parts)
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in stem).strip("_")[:60] or "download"


def _fresh_folder(dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    folder, number = dest_dir / name, 2
    while folder.exists():
        folder = dest_dir / f"{name}_{number}"
        number += 1
    folder.mkdir(parents=True)
    return folder
