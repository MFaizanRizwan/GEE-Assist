"""The data catalog: providers, routing and the download pipeline (network mocked)."""

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("shapefile")

from backend.business.catalog import (  # noqa: E402
    CatalogService,
    DivaGisProvider,
    EarthEngineProvider,
    GeofabrikProvider,
    GeoNamesProvider,
    HdxProvider,
    NaturalEarthProvider,
)
from backend.business.catalog import providers  # noqa: E402
from backend.business.catalog.downloader import _safe_extract  # noqa: E402
from backend.business.vector import VectorService  # noqa: E402
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
                           NaturalEarthProvider(), DivaGisProvider(), GeoNamesProvider(),
                           GeofabrikProvider(), HdxProvider()])


def test_lists_every_source_with_its_selectors(service):
    by_id = {s.id: s for s in service.list_sources()}
    assert set(by_id) == {"earth_engine", "natural_earth", "diva_gis", "geonames", "geofabrik", "hdx"}
    assert by_id["earth_engine"].needs_area and by_id["earth_engine"].datasets
    assert by_id["natural_earth"].scales and by_id["natural_earth"].datasets
    assert by_id["diva_gis"].datasets and by_id["diva_gis"].regions  # themes + countries
    assert by_id["geonames"].regions and not by_id["geonames"].datasets
    assert by_id["geofabrik"].regions
    assert by_id["hdx"].supports_search


def test_diva_gis_vector_builds_the_country_url(service, tmp_path, monkeypatch):
    captured = {}

    def fake_extract(url, dest_dir, on_progress=None, headers=None):
        captured["url"] = url
        return _write_fake_shapefile(dest_dir, "PAK_adm1")

    monkeypatch.setattr(providers.diva_gis, "download_and_extract", fake_extract)
    result = service.download(CatalogRequestDTO(source_id="diva_gis", dataset_id="admin", region_id="PAK"),
                              str(tmp_path))
    assert captured["url"] == "https://geodata.ucdavis.edu/diva/adm/PAK_adm.zip"
    assert result.open_in == "vector" and Path(result.primary_path).is_file()


def test_diva_gis_elevation_converts_to_geotiff_for_the_dem_page(service, tmp_path, monkeypatch):
    rasterio = pytest.importorskip("rasterio")
    from tests.test_terrain_service import east_ramp, write_dem

    def fake_extract(url, dest_dir, on_progress=None, headers=None):
        assert url == "https://geodata.ucdavis.edu/diva/msk_alt/PAK_msk_alt.zip"
        return [Path(write_dem(Path(dest_dir) / "PAK_msk_alt.tif", east_ramp()))]

    monkeypatch.setattr(providers.diva_gis, "download_and_extract", fake_extract)
    result = service.download(CatalogRequestDTO(source_id="diva_gis", dataset_id="elevation", region_id="PAK"),
                              str(tmp_path))
    assert result.open_in == "dem" and result.kind == "raster"
    with rasterio.open(result.primary_path) as src:
        assert src.count == 1  # a readable GeoTIFF for the DEM page


def test_geonames_writes_a_point_shapefile_for_idw(service, tmp_path, monkeypatch):
    def fake_extract(url, dest_dir, on_progress=None, headers=None):
        assert url == "https://download.geonames.org/export/dump/PK.zip"
        rows = [
            "1\tLahore\tLahore\t\t31.55\t74.34\tP\tPPLA\tPK\t\t04\t\t\t\t11000000\t\t217\tAsia/Karachi\t2020",
            "2\tMurree\tMurree\t\t33.9\t73.39\tP\tPPL\tPK\t\t04\t\t\t\t20000\t\t2291\tAsia/Karachi\t2020",
            "3\tPort\tPort\t\t24.8\t66.9\tP\tPPL\tPK\t\t02\t\t\t\t0\t\t-9999\tAsia/Karachi\t2020",
            "9\tK2\tK2\t\t35.88\t76.51\tT\tMT\tPK\t\t\t\t\t\t0\t\t8611\tAsia/Karachi\t2020",  # not a place (T)
        ]
        table = Path(dest_dir) / "PK.txt"
        table.write_text("\n".join(rows), encoding="utf-8")
        return [table]

    monkeypatch.setattr(providers.geonames, "download_and_extract", fake_extract)
    result = service.download(CatalogRequestDTO(source_id="geonames", region_id="PK"), str(tmp_path))
    assert result.open_in == "idw" and result.kind == "points"

    layer = VectorService().load_shapefile(result.primary_path)
    assert layer.kind == "point" and layer.feature_count == 3  # the mountain (class T) is excluded
    assert [f.name for f in layer.fields] == ["name", "population", "elevation"]
    # -9999 elevation became 0 (not a poisoned value for IDW)
    elevations = [f.attributes["elevation"] for f in layer.features]
    assert min(elevations) == 0 and max(elevations) == 2291


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


def test_each_kind_is_saved_in_its_own_folder(service, tmp_path, monkeypatch):
    from tests.test_terrain_service import east_ramp, write_dem

    monkeypatch.setattr(providers.natural_earth, "download_and_extract",
                        lambda url, dest_dir, on_progress=None, headers=None:
                        _write_fake_shapefile(dest_dir, "ne_110m_admin_0_countries"))
    monkeypatch.setattr(providers.diva_gis, "download_and_extract",
                        lambda url, dest_dir, on_progress=None, headers=None:
                        [Path(write_dem(Path(dest_dir) / "PAK_msk_alt.tif", east_ramp()))])

    def fake_geonames(url, dest_dir, on_progress=None, headers=None):
        table = Path(dest_dir) / "PK.txt"
        table.write_text("1\tX\tX\t\t31.5\t74.3\tP\tPPL\tPK\t\t04\t\t\t\t100\t\t200\ttz\t2020", encoding="utf-8")
        return [table]

    monkeypatch.setattr(providers.geonames, "download_and_extract", fake_geonames)
    pytest.importorskip("rasterio")

    vector = service.download(CatalogRequestDTO(source_id="natural_earth", dataset_id="countries", scale_id="110m"),
                              str(tmp_path))
    dem = service.download(CatalogRequestDTO(source_id="diva_gis", dataset_id="elevation", region_id="PAK"),
                           str(tmp_path))
    idw = service.download(CatalogRequestDTO(source_id="geonames", region_id="PK"), str(tmp_path))

    assert Path(vector.primary_path).is_relative_to(tmp_path / "Vector shapefiles")
    assert Path(dem.primary_path).is_relative_to(tmp_path / "DEM elevation")
    assert Path(idw.primary_path).is_relative_to(tmp_path / "IDW point data")


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
