"""GeoNames: populated places by country, as point data for IDW interpolation.

``https://download.geonames.org/export/dump/<ISO2>.zip`` holds a tab-separated dump; the
populated places (feature class ``P``) are written to a point shapefile with ``population`` and
``elevation`` fields — ready to interpolate on the IDW page. Big countries hold tens of thousands
of places, so the most-populated ones are kept, up to a cap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import shapefile  # pyshp

from backend.business.catalog.countries import options
from backend.business.catalog.downloader import ProgressCallback, download_and_extract
from backend.business.catalog.geojson_to_shapefile import WGS84_WKT
from backend.business.catalog.providers.base import CatalogProvider
from backend.dto.catalog_dto import OPEN_IN_IDW, CatalogRequestDTO, CatalogResultDTO, CatalogSourceDTO
from backend.exceptions import CatalogError

BASE_URL = "https://download.geonames.org/export/dump"
MAX_POINTS = 8000  # keep the most-populated places so IDW stays responsive


class GeoNamesProvider(CatalogProvider):
    id = "geonames"

    def source(self) -> CatalogSourceDTO:
        return CatalogSourceDTO(
            id=self.id, name="GeoNames places (for IDW)", kind="http",
            description="Populated places of a country as points with population and elevation — "
                        "interpolate either field on the IDW page.",
            regions=options("iso2"), attribution="GeoNames (CC BY)", default_open_in=OPEN_IN_IDW,
        )

    def download(self, request: CatalogRequestDTO, dest_dir: Path,
                 on_progress: Optional[ProgressCallback] = None) -> CatalogResultDTO:
        cc = (request.region_id or "").upper()
        if not cc:
            raise CatalogError("Choose a country first.")
        files = download_and_extract(f"{BASE_URL}/{cc}.zip", dest_dir, on_progress=on_progress)
        table = next((p for p in files if p.name.upper() == f"{cc}.TXT"), None)
        if table is None:
            raise CatalogError("The GeoNames download did not contain the expected data file.")

        places = _read_places(table)
        if not places:
            raise CatalogError(f"No populated places were found for {cc}.")
        places.sort(key=lambda row: row[3], reverse=True)  # most populated first
        places = places[:MAX_POINTS]

        shp = dest_dir / f"{cc}_places.shp"
        _write_points(places, shp)
        return CatalogResultDTO(
            paths=[str(p) for p in dest_dir.glob(f"{cc}_places.*")] + [str(p) for p in files],
            primary_path=str(shp), kind="points", open_in=OPEN_IN_IDW,
            name=f"GeoNames places · {cc}",
            notes=[f"{len(places):,} populated places with population & elevation — pick a field and Run IDW."])


def _read_places(table: Path) -> list[tuple[float, float, str, int, int]]:
    """(lon, lat, name, population, elevation) for every populated place (feature class P)."""
    rows: list[tuple[float, float, str, int, int]] = []
    with open(table, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split("\t")
            if len(parts) < 17 or parts[6] != "P":  # feature class P = city / village
                continue
            try:
                lat, lon = float(parts[4]), float(parts[5])
            except ValueError:
                continue
            population = max(0, _int(parts[14]))
            elevation = _elevation(parts[15]) or _elevation(parts[16])  # elevation, else the SRTM 'dem' value
            rows.append((lon, lat, parts[1][:50], population, elevation))
    return rows


def _write_points(places: list[tuple[float, float, str, int, int]], shp: Path) -> None:
    writer = shapefile.Writer(str(shp), shapeType=shapefile.POINT)
    writer.field("name", "C", 50)
    writer.field("population", "N", 12)
    writer.field("elevation", "N", 8)
    for lon, lat, name, population, elevation in places:
        writer.point(lon, lat)
        writer.record(name, population, elevation)
    writer.close()
    shp.with_suffix(".prj").write_text(WGS84_WKT, encoding="utf-8")


def _int(text: str) -> int:
    try:
        return int(text)
    except (ValueError, TypeError):
        return 0


def _elevation(text: str) -> int:
    """An elevation in metres, or 0 when GeoNames has none (it stores -9999 for "unknown")."""
    value = _int(text)
    return value if value > -1000 else 0
