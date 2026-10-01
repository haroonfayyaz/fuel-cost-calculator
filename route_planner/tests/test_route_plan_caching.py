"""
Caching integration: external ORS calls vs local fuel recompute.

Expected provider HTTP calls (uncached):
- coordinate endpoints: 1 directions POST
- text endpoints: 2 geocode GET + 1 directions POST
- repeated identical request: 0 provider calls (geocode + route cached)
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache

from route_planner.models import FuelStation
from route_planner.services.route_planner import RoutePlanner
from route_planner.services.routing.open_route_service import OpenRouteServiceProvider
from route_planner.tests.test_open_route_service import _response

ROUTE_GEOMETRY = {
    "type": "LineString",
    "coordinates": [[-105.0, 39.0], [-104.0, 39.0]],
}
ROUTE_DISTANCE_MILES = 600.0
ROUTE_DISTANCE_METERS = ROUTE_DISTANCE_MILES / 0.000621371
START_LAT, START_LON = 39.0, -105.0
FINISH_LAT, FINISH_LON = 39.0, -104.0


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def mock_routing_provider():
    session = MagicMock()

    def handler(*, method, url, params=None, **kwargs):
        if method == "GET" and "pelias" in url:
            text = (params or {}).get("text", "").casefold()
            if "finish" in text:
                coordinates = [FINISH_LON, FINISH_LAT]
                label = "Finish, CO, USA"
            else:
                coordinates = [START_LON, START_LAT]
                label = "Start, CO, USA"
            return _response(
                200,
                {
                    "features": [
                        {
                            "geometry": {"coordinates": coordinates},
                            "properties": {"label": label, "country_code": "US"},
                        }
                    ]
                },
            )
        if method == "POST" and "directions" in url:
            return _response(
                200,
                {
                    "features": [
                        {
                            "geometry": ROUTE_GEOMETRY,
                            "properties": {
                                "summary": {
                                    "distance": ROUTE_DISTANCE_METERS,
                                    "duration": 36000.0,
                                }
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request {method} {url}")

    session.request.side_effect = lambda **kwargs: handler(**kwargs)

    provider = OpenRouteServiceProvider(
        base_url="https://api.heigit.org",
        api_key="test-key",
        geocode_cache_timeout_seconds=3600,
        route_cache_timeout_seconds=3600,
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
        session=session,
    )
    return provider, session


def _provider_calls(session):
    geocode = 0
    directions = 0
    for call in session.request.call_args_list:
        kwargs = call.kwargs
        if kwargs.get("method") == "GET" and "pelias" in kwargs.get("url", ""):
            geocode += 1
        if kwargs.get("method") == "POST" and "directions" in kwargs.get("url", ""):
            directions += 1
    return geocode, directions


@pytest.fixture
def corridor_station(db):
    return FuelStation.objects.create(
        opis_truckstop_id="cache-test",
        name="Corridor Stop",
        address="I-40",
        city="Denver",
        state="CO",
        rack_id="1",
        retail_price=Decimal("3.000000"),
        location=Point(-104.333333, 39.0, srid=4326),
        geocoding_status=FuelStation.GeocodingStatus.MATCHED,
        source_line_number=424242,
    )


@pytest.fixture
def planner(mock_routing_provider):
    provider, _session = mock_routing_provider
    return RoutePlanner(provider)


def test_coordinate_request_provider_call_counts(client, planner, mock_routing_provider, corridor_station):
    _provider, session = mock_routing_provider
    payload = {
        "start": {"latitude": START_LAT, "longitude": START_LON},
        "finish": {"latitude": FINISH_LAT, "longitude": FINISH_LON},
    }

    with patch("route_planner.views_fuel_plan.get_route_planner", return_value=planner):
        first = client.post("/api/v1/routes/fuel-plan/", payload, content_type="application/json")
        second = client.post("/api/v1/routes/fuel-plan/", payload, content_type="application/json")

    assert first.status_code == 200
    assert second.status_code == 200
    geocode_calls, directions_calls = _provider_calls(session)
    assert geocode_calls == 0
    assert directions_calls == 1


def test_text_request_provider_call_counts(client, planner, mock_routing_provider, corridor_station):
    _provider, session = mock_routing_provider
    payload = {"start": "Route start, CO", "finish": "Route finish, CO"}

    with patch("route_planner.views_fuel_plan.get_route_planner", return_value=planner):
        first = client.post("/api/v1/routes/fuel-plan/", payload, content_type="application/json")
        second = client.post("/api/v1/routes/fuel-plan/", payload, content_type="application/json")

    assert first.status_code == 200
    assert second.status_code == 200
    geocode_calls, directions_calls = _provider_calls(session)
    assert geocode_calls == 2
    assert directions_calls == 1


def test_fuel_price_change_with_cached_route(client, planner, mock_routing_provider, corridor_station):
    _provider, session = mock_routing_provider
    payload = {
        "start": {"latitude": START_LAT, "longitude": START_LON},
        "finish": {"latitude": FINISH_LAT, "longitude": FINISH_LON},
    }

    with patch("route_planner.views_fuel_plan.get_route_planner", return_value=planner):
        first = client.post("/api/v1/routes/fuel-plan/", payload, content_type="application/json")
        corridor_station.retail_price = Decimal("5.000000")
        corridor_station.save(update_fields=["retail_price", "updated_at"])
        second = client.post("/api/v1/routes/fuel-plan/", payload, content_type="application/json")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["total_fuel_cost"] != second.json()["total_fuel_cost"]
    _, directions_calls = _provider_calls(session)
    assert directions_calls == 1
