"""Humanitarian Data Exchange (HDX): search its CKAN catalogue and download a shapefile.

HDX datasets vary a lot, so this is best-effort: it searches by text, then picks the first
resource that is a zipped shapefile (or GeoJSON, which it converts). If a search turns up no
vector resource it says so, with the dataset titles it did find.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from backend.business.catalog.downloader import ProgressCallback, download_and_extract, fetch_json
from backend.business.catalog.geojson_to_shapefile import write_geojson
from backend.business.catalog.providers.base import CatalogProvider, first_shapefile
from backend.dto.catalog_dto import (
    OPEN_IN_VECTOR,
    CatalogRequestDTO,
    CatalogResultDTO,
    CatalogSourceDTO,
)
from backend.exceptions import CatalogError

SEARCH_URL = "https://data.humdata.org/api/3/action/package_search"
_SHP_FORMATS = {"shp", "zipped shapefile", "shapefile", "geopackage", "zipped geopackage"}
_GEOJSON_FORMATS = {"geojson", "json"}


class HdxProvider(CatalogProvider):
    id = "hdx"

    def source(self) -> CatalogSourceDTO:
        return CatalogSourceDTO(
            id=self.id, name="Humanitarian Data Exchange", kind="search",
            description="Search HDX for vector datasets (admin boundaries, settlements, infrastructure) "
                        "and download the first shapefile found.",
            supports_search=True, attribution="Humanitarian Data Exchange (HDX)",
        )

    def download(self, request: CatalogRequestDTO, dest_dir: Path,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        query = request.query.strip()
        if not query:
            raise CatalogError("Type what to search HDX for (e.g. 'Pakistan admin boundaries').")
        data = fetch_json(SEARCH_URL, params={"q": query, "rows": 10})
        results = (data.get("result") or {}).get("results") or []
        if not results:
            raise CatalogError(f"HDX found no datasets for '{query}'.")

        resource, dataset_title = _best_resource(results)
        if resource is None:
            titles = ", ".join(str(d.get("title", "")) for d in results[:5])
            raise CatalogError(f"None of the HDX results for '{query}' had a shapefile. Found: {titles}.")

        url = resource["url"]
        files = download_and_extract(url, dest_dir, on_progress=on_progress)
        shp = first_shapefile([Path(f) for f in files])
        if shp is None:  # a GeoJSON download: convert it to a shapefile
            shp = _geojson_to_shp(files, dest_dir, query)
            files = [str(p) for p in Path(shp).parent.glob(Path(shp).stem + ".*")]
        return CatalogResultDTO(
            paths=[str(p) for p in files], primary_path=str(shp), kind="vector", open_in=OPEN_IN_VECTOR,
            name=f"HDX · {dataset_title}"[:80], notes=[f"From HDX dataset '{dataset_title}'."],
        )


def _best_resource(results: list[dict]) -> tuple[Optional[dict], str]:
    """The first shapefile (preferred) or GeoJSON resource across the datasets, and its dataset title."""
    fallback: tuple[Optional[dict], str] = (None, "")
    for dataset in results:
        title = str(dataset.get("title", "dataset"))
        for resource in dataset.get("resources", []) or []:
            fmt = str(resource.get("format", "")).strip().lower()
            url = str(resource.get("url", "")).lower()
            if not resource.get("url"):
                continue
            if fmt in _SHP_FORMATS or url.endswith(".shp.zip") or (url.endswith(".zip") and "shp" in url):
                return resource, title
            if fallback[0] is None and (fmt in _GEOJSON_FORMATS or url.endswith(".geojson")):
                fallback = (resource, title)
    return fallback


def _geojson_to_shp(files: list[Path], dest_dir: Path, query: str) -> str:
    geojson_file = next((Path(f) for f in files if Path(f).suffix.lower() in (".geojson", ".json")), None)
    if geojson_file is None:
        raise CatalogError("The HDX download was neither a shapefile nor GeoJSON.")
    try:
        data = json.loads(geojson_file.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"The HDX GeoJSON could not be read: {exc}") from exc
    stem = "".join(c if c.isalnum() else "_" for c in query)[:30] or "hdx"
    written = write_geojson(data, str(dest_dir / f"{stem}.shp"))
    return written[0]
