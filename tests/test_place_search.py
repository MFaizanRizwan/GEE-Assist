"""AOI from a place name: Nominatim client, RequestService.search_place, simplification (no network)."""

from __future__ import annotations

import json
import math

import httpx
import pytest

from backend.business.request import RequestService
from backend.business.request.geojson_utils import count_vertices, simplify_geometry, validate_geometry
from backend.business.request.request_service import MAX_PLACE_VERTICES
from backend.data.clients.nominatim_client import NominatimClient
from backend.data.data_facade import DataFacade
from backend.dto import PlaceDTO
from backend.exceptions import PlaceSearchError, ValidationError

SQUARE = {"type": "Polygon", "coordinates": [[[74.2, 31.4], [74.5, 31.4], [74.5, 31.7], [74.2, 31.7], [74.2, 31.4]]]}
POINT = {"type": "Point", "coordinates": [74.3, 31.5]}


def ring(lon: float, lat: float, radius: float, points: int) -> list[list[float]]:
    coords = [[lon + radius * math.cos(2 * math.pi * i / points), lat + radius * math.sin(2 * math.pi * i / points)]
              for i in range(points)]
    return coords + [list(coords[0])]


def nominatim_item(name: str, geojson: dict, kind: str = "city", display: str | None = None) -> dict:
    return {"name": name, "display_name": display or f"{name}, Punjab, Pakistan", "addresstype": kind, "geojson": geojson}


# ------------------------------------------------------------------ NominatimClient
def client_answering(handler, **kwargs) -> NominatimClient:
    return NominatimClient(transport=httpx.MockTransport(handler), sleep=lambda _s: None, **kwargs)


def test_client_asks_for_boundaries_and_reads_places():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        seen["agent"] = request.headers["User-Agent"]
        return httpx.Response(200, json=[nominatim_item("Lahore", SQUARE), {"bad": "item"}])

    places = client_answering(handler).search("Lahore", limit=3)

    assert seen["q"] == "Lahore" and seen["polygon_geojson"] == "1" and seen["limit"] == "3"
    assert seen["agent"] == "GEE-Assist-Desktop"
    assert places == [PlaceDTO("Lahore", "Lahore, Punjab, Pakistan", "city", json.dumps(SQUARE))]


@pytest.mark.parametrize("response, message", [
    (httpx.Response(429), "busy"),
    (httpx.Response(503), "HTTP 503"),
    (httpx.Response(200, text="<html>"), "unreadable"),
    (httpx.Response(200, json={"error": "x"}), "unreadable"),
])
def test_client_turns_bad_answers_into_place_search_errors(response, message):
    with pytest.raises(PlaceSearchError, match=message):
        client_answering(lambda _r: response).search("Lahore")


def test_client_reports_an_unreachable_service():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(PlaceSearchError, match="internet connection"):
        client_answering(handler).search("Lahore")


def test_client_spaces_requests_a_second_apart():
    now, waits = [100.0], []
    client = NominatimClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=[])),
        clock=lambda: now[0], sleep=waits.append,
    )
    client.search("a")
    now[0] += 0.25
    client.search("b")
    assert waits == [pytest.approx(0.75)]


def test_data_facade_without_a_geocoder_says_so():
    with pytest.raises(PlaceSearchError, match="not set up"):
        DataFacade(gemini_client=None).search_places("Lahore")


# ------------------------------------------------------------------ RequestService.search_place
class FakeGeocodingFacade:
    def __init__(self, places):
        self.places, self.queries = places, []

    def search_places(self, query):
        self.queries.append(query)
        return self.places


def test_search_keeps_only_places_with_a_boundary():
    facade = FakeGeocodingFacade([
        PlaceDTO("Lahore", "Lahore (point)", "city", json.dumps(POINT)),
        PlaceDTO("Lahore", "Lahore, Punjab, Pakistan", "city", json.dumps(SQUARE)),
        PlaceDTO("Lahore", "Lahore, Punjab, Pakistan", "city", json.dumps(SQUARE)),  # duplicate
        PlaceDTO("Broken", "Broken", "city", "not json"),
    ])
    places = RequestService(data_facade=facade).search_place("  Lahore \n Pakistan ")

    assert facade.queries == ["Lahore Pakistan"]
    assert [p.display_name for p in places] == ["Lahore, Punjab, Pakistan"]
    assert json.loads(places[0].aoi) == SQUARE  # small outlines are kept exactly


def test_search_without_any_boundary_explains_what_to_try():
    facade = FakeGeocodingFacade([PlaceDTO("Nowhere", "Nowhere", "hamlet", json.dumps(POINT))])
    with pytest.raises(PlaceSearchError, match="No boundary found"):
        RequestService(data_facade=facade).search_place("Nowhere")


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_search_rejects_empty_or_overlong_names(name):
    with pytest.raises(ValidationError):
        RequestService(data_facade=FakeGeocodingFacade([])).search_place(name)


def test_search_without_a_data_facade_is_unavailable():
    with pytest.raises(PlaceSearchError):
        RequestService().search_place("Lahore")


def test_search_simplifies_very_detailed_boundaries():
    country = {"type": "Polygon", "coordinates": [ring(70, 30, 5, 40_000)]}
    facade = FakeGeocodingFacade([PlaceDTO("Big", "Big country", "country", json.dumps(country))])
    geometry = json.loads(RequestService(data_facade=facade).search_place("Big")[0].aoi)
    assert count_vertices(geometry) <= MAX_PLACE_VERTICES and validate_geometry(geometry) is None


# ------------------------------------------------------------------ simplify_geometry
def test_simplify_leaves_small_outlines_alone():
    assert simplify_geometry(SQUARE, 100) is SQUARE


def test_simplify_keeps_the_outline_close_and_valid():
    circle = {"type": "Polygon", "coordinates": [ring(70, 30, 1, 10_000)]}
    simplified = simplify_geometry(circle, 500)
    outer = simplified["coordinates"][0]
    assert count_vertices(simplified) <= 500 and validate_geometry(simplified) is None
    assert all(abs(math.hypot(lon - 70, lat - 30) - 1) < 0.01 for lon, lat in outer)


def test_simplify_drops_tiny_islands_but_never_the_main_area():
    mainland = [ring(70, 30, 5, 3000)]
    islands = [[ring(80 + i * 0.01, 10, 0.000001, 8)] for i in range(50)]
    geometry = {"type": "MultiPolygon", "coordinates": [*islands, mainland]}
    simplified = simplify_geometry(geometry, 200)
    assert simplified["type"] == "Polygon" and validate_geometry(simplified) is None
    assert count_vertices(simplified) <= 200


# ------------------------------------------------------------------ a city, its district and its division
def _square(size: float) -> str:
    return json.dumps({"type": "Polygon", "coordinates": [[[73, 31], [73 + size, 31], [73 + size, 31 + size],
                                                           [73, 31 + size], [73, 31]]]})


class HierarchyFacade:
    """Answers like the real service: a name gives one merged match; the levels by their full names."""

    HIERARCHY = "Faisalabad District, Faisalabad Division, Punjab, Pakistan"

    def __init__(self, city_has_boundary=True):
        self.queries = []
        self.answers = {
            "Faisalabad": [PlaceDTO("Faisalabad City Tehsil", f"Faisalabad City Tehsil, {self.HIERARCHY}", "city",
                                    _square(0.1) if city_has_boundary else json.dumps(POINT))],
            "Faisalabad District": [
                PlaceDTO("Ismail City", f"Ismail City, Faisalabad City Tehsil, {self.HIERARCHY}", "neighbourhood",
                         _square(0.01)),                                   # not the district: skipped
                PlaceDTO("Faisalabad District", self.HIERARCHY, "district", _square(0.8))],
            "Faisalabad Division": [PlaceDTO("Faisalabad Division", "Faisalabad Division, Punjab, Pakistan",
                                             "division", _square(2.0))],
            "Punjab": [PlaceDTO("Punjab", "Punjab, Pakistan", "province", _square(6.0))],
        }

    def search_places(self, query):
        self.queries.append(query)
        return self.answers.get(query, [])


def test_a_city_search_also_offers_its_district_and_division_smallest_first():
    facade = HierarchyFacade()
    places = RequestService(data_facade=facade).search_place("Faisalabad")
    assert [(p.name, p.kind) for p in places] == [
        ("Faisalabad City Tehsil", "city"), ("Faisalabad District", "district"), ("Faisalabad Division", "division")]
    # only the levels that carry the name are looked up (not "Punjab", not "Pakistan")
    assert facade.queries == ["Faisalabad", "Faisalabad District", "Faisalabad Division"]


def test_a_city_mapped_only_as_a_point_still_finds_its_district():
    places = RequestService(data_facade=HierarchyFacade(city_has_boundary=False)).search_place("Faisalabad")
    assert [p.kind for p in places] == ["district", "division"]


def test_a_failing_extra_level_never_loses_the_main_match():
    facade = HierarchyFacade()

    def flaky(query):
        if query != "Faisalabad":
            raise PlaceSearchError("busy")
        return HierarchyFacade.search_places(facade, query)

    facade.search_places = flaky
    assert [p.kind for p in RequestService(data_facade=facade).search_place("Faisalabad")] == ["city"]


def test_the_client_names_administrative_levels_as_people_say_them():
    def handler(_request):
        return httpx.Response(200, json=[
            nominatim_item("Faisalabad City Tehsil", SQUARE, "subdistrict"),
            nominatim_item("Okara Tehsil", SQUARE, "subdistrict"),
            nominatim_item("Lahore District", SQUARE, "county"),
            nominatim_item("Punjab", SQUARE, "state")])

    assert [p.kind for p in client_answering(handler).search("x")] == ["city", "tehsil", "district", "province"]
