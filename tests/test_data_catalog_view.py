"""The Data Catalog page (no window on screen; facade and network mocked)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
pytest.importorskip("shapefile")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.catalog import (  # noqa: E402
    CatalogService,
    EarthEngineProvider,
    GeofabrikProvider,
    HdxProvider,
    NaturalEarthProvider,
)
from backend.dto.catalog_dto import CatalogResultDTO  # noqa: E402
from backend.dto.place_dto import PlaceDTO  # noqa: E402
from frontend.views import data_catalog_view as view_module  # noqa: E402
from frontend.views.data_catalog_view import DataCatalogView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _run_now(owner, fn, *args, on_success=None, on_error=None):
    try:
        result = fn(*args)
    except Exception as exc:
        if on_error:
            on_error(exc)
    else:
        if on_success:
            on_success(result)


@pytest.fixture
def page(app, monkeypatch):
    monkeypatch.setattr(view_module, "run_task", _run_now)
    sources = CatalogService([EarthEngineProvider(lambda a, g, n: {}), NaturalEarthProvider(),
                              GeofabrikProvider(), HdxProvider()]).list_sources()
    facade = MagicMock()
    facade.get_current_project.return_value = None
    facade.list_data_sources.return_value = sources
    view = DataCatalogView(facade)
    view.load_sources()  # the real page does this on first show
    yield view, facade
    view.deleteLater()


def _select_source(view, source_id):
    index = [view.source_box.itemData(i) for i in range(view.source_box.count())].index(source_id)
    view.source_box.setCurrentIndex(index)


def test_source_controls_switch_with_the_provider(page):
    view, _ = page
    _select_source(view, "natural_earth")
    assert not view._rows["dataset"][1].isHidden() and not view._rows["scale"][1].isHidden()
    assert view._rows["region"][1].isHidden() and view._rows["query"][1].isHidden()

    _select_source(view, "geofabrik")
    assert not view._rows["region"][1].isHidden() and view._rows["scale"][1].isHidden()

    _select_source(view, "hdx")
    assert not view._rows["query"][1].isHidden()

    _select_source(view, "earth_engine")
    assert not view._rows["area"][1].isHidden() and not view._rows["max"][1].isHidden()


def test_downloading_natural_earth_sends_the_right_request_and_offers_open(page):
    view, facade = page
    facade.download_dataset.return_value = CatalogResultDTO(
        paths=["C:/data/ne/ne.shp"], primary_path="C:/data/ne/ne.shp", kind="vector", open_in="vector",
        name="Natural Earth · Countries (110m)", notes=["ok"])
    _select_source(view, "natural_earth")
    _set_combo(view.dataset_box, "countries")
    _set_combo(view.scale_box, "110m")
    view.download()

    request = facade.download_dataset.call_args.args[0]
    assert request.source_id == "natural_earth" and request.dataset_id == "countries" and request.scale_id == "110m"
    assert not view.open_button.isHidden()

    opened = []
    view.open_requested.connect(lambda path, where: opened.append((path, where)))
    view.open_button.click()
    assert opened == [("C:/data/ne/ne.shp", "vector")]


def test_earth_engine_needs_an_area_before_downloading(page):
    view, facade = page
    _select_source(view, "earth_engine")
    view.download()
    assert not facade.download_dataset.called  # blocked: no area chosen
    assert "place" in view.banner.text().lower() or "area" in view.banner.text().lower()


def test_place_search_sets_the_area_of_interest(page):
    view, facade = page
    facade.search_place.return_value = [PlaceDTO(name="Punjab", display_name="Punjab, Pakistan", kind="state",
                                                 aoi='{"type":"Polygon","coordinates":[[[71,30],[75,30],[75,33],[71,33],[71,30]]]}')]
    _select_source(view, "earth_engine")
    view.place_edit.setText("Punjab")
    view.search_place()
    assert view._aoi_geojson.startswith('{"type":"Polygon"')
    assert view._area_name == "Punjab"
    assert "Punjab" in view.area_label.text()


def _set_combo(box, data):
    box.setCurrentIndex([box.itemData(i) for i in range(box.count())].index(data))
