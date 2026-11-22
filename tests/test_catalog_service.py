"""The data catalog: providers, routing and the download pipeline (network mocked)."""

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("shapefile")

from backend.business.catalog import (  # noqa: E402
    CatalogService,
    EarthEngineProvider,
    GeofabrikProvider,
    HdxProvider,
    NaturalEarthProvider,
)
from backend.business.catalog import providers  # noqa: E402
from backend.business.catalog.downloader import _safe_extract  # noqa: E402
from backend.business.catalog.geojson_to_shapefile import write_geojson  # noqa: E402
from backend.dto.catalog_dto import CatalogRequestDTO  # noqa: E402
from backend.exceptions import CatalogError  # noqa: E402


def _poly_fc():
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "Pakistan"},
         "geometry": {"type": "Polygon", "coordinates": [[[60, 23], [77, 23], [77, 37], [60, 37], [60, 23]]]}}]}


def _write_fake_shapefile(dest_dir, stem):
    return [Path(p) for p in write_geojson(_poly_fc(), str(Path(dest_dir) / f"{stem}.shp"))]


@pytest.fixture
def service():
    return CatalogService([EarthEngineProvider(lambda a, g, n, c: _poly_fc()),
                           NaturalEarthProvider(), GeofabrikProvider(), HdxProvider()])


def test_lists_every_source_with_its_selectors(service):
    by_id = {s.id: s for s in service.list_sources()}
    assert set(by_id) == {"earth_engine", "natural_earth", "geofabrik", "hdx"}
    assert by_id["earth_engine"].needs_area and by_id["earth_engine"].datasets
    assert by_id["natural_earth"].scales and by_id["natural_earth"].datasets
    assert by_id["geofabrik"].regions
    assert by_id["hdx"].supports_search


def test_earth_engine_download_writes_a_shapefile(service, tmp_path):
    result = service.download(CatalogRequestDTO(source_id="earth_engine", dataset_id="admin0",
                              aoi_geojson='{"type":"Polygon","coordinates":[[[60,23],[77,23],[77,37],[60,37],[60,23]]]}',
                              area_name="Pakistan"), str(tmp_path))
    assert result.open_in == "vector" and result.primary_path.endswith(".shp")
    assert Path(result.primary_path).is_file()


def test_earth_engine_requires_an_area(service, tmp_path):
    with pytest.raises(CatalogError, match="area of interest"):
        service.download(CatalogRequestDTO(source_id="earth_engine", dataset_id="admin0"), str(tmp_path))


def test_natural_earth_download_uses_the_scale_and_layer(service, tmp_path, monkeypatch):
    captured = {}

    def fake_extract(url, dest_dir, on_progress=None, headers=None):
        captured["url"] = url
        return _write_fake_shapefile(dest_dir, "ne_110m_admin_0_countries")

    monkeypatch.setattr(providers.natural_earth, "download_and_extract", fake_extract)
    result = service.download(CatalogRequestDTO(source_id="natural_earth", dataset_id="countries", scale_id="110m"),
                              str(tmp_path))
    assert captured["url"] == "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"
    assert Path(result.primary_path).is_file()


def test_geofabrik_builds_the_region_url(service, tmp_path, monkeypatch):
    captured = {}

    def fake_extract(url, dest_dir, on_progress=None, headers=None):
        captured["url"] = url
        return _write_fake_shapefile(dest_dir, "gis_osm_roads_free_1")

    monkeypatch.setattr(providers.geofabrik, "download_and_extract", fake_extract)
    service.download(CatalogRequestDTO(source_id="geofabrik", region_id="pakistan"), str(tmp_path))
    assert captured["url"] == "https://download.geofabrik.de/asia/pakistan-latest-free.shp.zip"


def test_hdx_searches_and_downloads_the_first_shapefile(service, tmp_path, monkeypatch):
    def fake_json(url, params=None, timeout=30.0):
        return {"result": {"results": [{"title": "Pakistan Admin Boundaries", "resources": [
            {"format": "CSV", "url": "https://x/data.csv"},
            {"format": "SHP", "url": "https://x/boundaries.shp.zip"}]}]}}

    def fake_extract(url, dest_dir, on_progress=None, headers=None):
        assert url == "https://x/boundaries.shp.zip"
        return _write_fake_shapefile(dest_dir, "boundaries")

    monkeypatch.setattr(providers.hdx, "fetch_json", fake_json)
    monkeypatch.setattr(providers.hdx, "download_and_extract", fake_extract)
    result = service.download(CatalogRequestDTO(source_id="hdx", query="Pakistan admin"), str(tmp_path))
    assert "Pakistan Admin Boundaries" in result.name
    assert Path(result.primary_path).is_file()


def test_hdx_reports_when_nothing_is_a_shapefile(service, tmp_path, monkeypatch):
    monkeypatch.setattr(providers.hdx, "fetch_json", lambda url, params=None, timeout=30.0:
                        {"result": {"results": [{"title": "Report PDF", "resources": [
                            {"format": "PDF", "url": "https://x/report.pdf"}]}]}})
    with pytest.raises(CatalogError, match="shapefile"):
        service.download(CatalogRequestDTO(source_id="hdx", query="report"), str(tmp_path))


def test_unknown_source_is_rejected(service, tmp_path):
    with pytest.raises(CatalogError, match="Unknown data source"):
        service.download(CatalogRequestDTO(source_id="nope"), str(tmp_path))


def test_downloads_go_into_fresh_folders(service, tmp_path, monkeypatch):
    monkeypatch.setattr(providers.natural_earth, "download_and_extract",
                        lambda url, dest_dir, on_progress=None, headers=None:
                        _write_fake_shapefile(dest_dir, "ne_110m_admin_0_countries"))
    req = CatalogRequestDTO(source_id="natural_earth", dataset_id="countries", scale_id="110m")
    first = service.download(req, str(tmp_path))
    second = service.download(req, str(tmp_path))
    assert Path(first.primary_path).parent != Path(second.primary_path).parent


def test_safe_extract_blocks_path_traversal(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("inside.shp", b"ok")
        zf.writestr("../escape.txt", b"bad")
    out = tmp_path / "out"
    out.mkdir()
    extracted = _safe_extract(archive, out)
    assert [p.name for p in extracted] == ["inside.shp"]
    assert not (tmp_path / "escape.txt").exists()
