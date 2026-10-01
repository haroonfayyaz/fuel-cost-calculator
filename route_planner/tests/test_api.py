"""HTTP API, health, demo UI, and routing cache integration tests."""

import json
from decimal import Decimal
from unittest.mock import create_autospec, patch

import pytest

from route_planner.services.route_planner import (
    PlannedFuelStop,
    RoutePlanAssumptions,
    RoutePlanDiagnostics,
    RoutePlanNotFeasibleError,
    RoutePlanResult,
    RoutePlanner,
    RouteSummary,
    VehicleProfile,
)
from route_planner.services.routing.base import (
    GeocodedLocation,
    GeocodingNotFoundError,
    GeocodingOutsideUSAError,
    RoutingBadRequestError,
    RoutingInvalidResponseError,
    RoutingNotFoundError,
    RoutingProvider,
    RoutingRateLimitError,
    RoutingServerError,
)

URL = "/api/v1/routes/fuel-plan/"

ROUTE_GEOMETRY = {
    "type": "LineString",
    "coordinates": [[-96.797, 32.7767], [-118.2437, 34.0522]],
}


def _sample_result(*, with_stop: bool = True) -> RoutePlanResult:
    stops = ()
    purchased = Decimal("0")
    total_cost = Decimal("0")
    if with_stop:
        stops = (
            PlannedFuelStop(
                station_id=123,
                name="Test Stop",
                address="1 Main St",
                latitude=35.1,
                longitude=-101.4,
                route_mile=Decimal("470.2"),
                price_per_gallon=Decimal("2.899"),
                gallons_before=Decimal("10"),
                gallons_purchased=Decimal("31.4"),
                gallons_after=Decimal("41.4"),
                cost=Decimal("91.0286"),
            ),
        )
        purchased = Decimal("31.4")
        total_cost = Decimal("91.0286")

    return RoutePlanResult(
        route=RouteSummary(
            geometry=ROUTE_GEOMETRY,
            distance_miles=1427.35,
            duration_seconds=74000.0,
        ),
        vehicle=VehicleProfile(
            mpg=10,
            maximum_range_miles=500,
            tank_capacity_gallons=Decimal("50"),
        ),
        fuel_stops=stops,
        fuel_consumed_gallons=Decimal("142.735"),
        fuel_purchased_gallons=purchased,
        total_fuel_cost=total_cost,
        assumptions=RoutePlanAssumptions(),
        diagnostics=RoutePlanDiagnostics(candidate_station_count=3),
    )


@pytest.fixture
def mock_planner():
    with patch("route_planner.views_fuel_plan.get_route_planner") as get_planner:
        planner = get_planner.return_value
        planner.plan.return_value = _sample_result()
        yield planner


def test_success_with_text_locations(client, mock_planner):
    response = client.post(
        URL,
        data={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["type"] == "LineString"
    assert body["distance_miles"] == 1427.35
    assert body["duration_seconds"] == 74000.0
    assert body["vehicle"]["mpg"] == 10
    assert body["vehicle"]["tank_capacity_gallons"] == "50"
    assert body["fuel_consumed_gallons"] == "142.735"
    assert body["assumptions"]["starts_with_full_tank"] is True
    assert len(body["fuel_stops"]) == 1
    stop = body["fuel_stops"][0]
    assert stop["station_id"] == 123
    assert stop["station_name"] == "Test Stop"
    assert stop["price_per_gallon"] == "2.899"
    assert stop["gallons_purchased"] == "31.4"
    assert "fuel_cost" in stop
    mock_planner.plan.assert_called_once()


def test_success_with_coordinate_locations(client, mock_planner):
    response = client.post(
        URL,
        data={
            "start": {"latitude": 32.7767, "longitude": -96.797},
            "finish": {"latitude": 34.0522, "longitude": -118.2437},
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    mock_planner.plan.assert_called_once()


def test_missing_start_returns_400(client):
    response = client.post(
        URL,
        data={"finish": "Los Angeles, CA"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "start" in response.json()


def test_missing_finish_returns_400(client):
    response = client.post(
        URL,
        data={"start": "Dallas, TX"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "finish" in response.json()


def test_invalid_latitude_returns_400(client):
    response = client.post(
        URL,
        data={
            "start": {"latitude": 95.0, "longitude": -96.0},
            "finish": {"latitude": 34.0, "longitude": -118.0},
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "start" in response.json()


def test_invalid_longitude_returns_400(client):
    response = client.post(
        URL,
        data={
            "start": {"latitude": 32.0, "longitude": -200.0},
            "finish": {"latitude": 34.0, "longitude": -118.0},
        },
        content_type="application/json",
    )
    assert response.status_code == 400


def test_invalid_location_object_returns_400(client):
    response = client.post(
        URL,
        data={"start": {}, "finish": "Los Angeles, CA"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "start" in response.json()


def test_blank_location_string_returns_400(client):
    response = client.post(
        URL,
        data={"start": "   ", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )
    assert response.status_code == 400


def test_non_us_coordinates_return_400(client):
    routing = create_autospec(RoutingProvider, instance=True)
    with patch(
        "route_planner.views_fuel_plan.get_route_planner",
        return_value=RoutePlanner(routing),
    ):
        response = client.post(
            URL,
            data={
                "start": {"latitude": 51.5, "longitude": -0.1},
                "finish": {"latitude": 34.0, "longitude": -118.0},
            },
            content_type="application/json",
        )

    assert response.status_code == 400
    assert "United States" in response.json()["detail"]
    routing.get_route.assert_not_called()


def test_same_start_and_finish_returns_400(client):
    routing = create_autospec(RoutingProvider, instance=True)
    with patch(
        "route_planner.views_fuel_plan.get_route_planner",
        return_value=RoutePlanner(routing),
    ):
        response = client.post(
            URL,
            data={
                "start": {"latitude": 32.7767, "longitude": -96.797},
                "finish": {"latitude": 32.7767, "longitude": -96.797},
            },
            content_type="application/json",
        )

    assert response.status_code == 400
    assert "same location" in response.json()["detail"]
    routing.geocode_location.assert_not_called()
    routing.get_route.assert_not_called()


def test_route_not_feasible_returns_422(client, mock_planner):
    mock_planner.plan.side_effect = RoutePlanNotFeasibleError("gap")

    response = client.post(
        URL,
        data={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert "cannot be completed" in response.json()["detail"]


def test_geocoding_not_found_returns_400(client, mock_planner):
    mock_planner.plan.side_effect = GeocodingNotFoundError("missing")

    response = client.post(
        URL,
        data={"start": "Nowhere, ZZ", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "resolve" in response.json()["detail"].lower()


def test_geocoding_outside_usa_returns_400(client, mock_planner):
    mock_planner.plan.side_effect = GeocodingOutsideUSAError("outside")

    response = client.post(
        URL,
        data={"start": "Paris, France", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "United States" in response.json()["detail"]


def test_routing_not_found_returns_404(client, mock_planner):
    mock_planner.plan.side_effect = RoutingNotFoundError("missing")

    response = client.post(
        URL,
        data={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert "route" in response.json()["detail"].lower()


def test_routing_bad_request_returns_400(client, mock_planner):
    mock_planner.plan.side_effect = RoutingBadRequestError("bad")

    response = client.post(
        URL,
        data={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 400


def test_rate_limit_returns_429(client, mock_planner):
    mock_planner.plan.side_effect = RoutingRateLimitError("limit")

    response = client.post(
        URL,
        data={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()


def test_routing_server_error_returns_503(client, mock_planner):
    mock_planner.plan.side_effect = RoutingServerError("down")

    response = client.post(
        URL,
        data={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 503
    assert "detail" in response.json()
    assert "ORS" not in response.json()["detail"]


def test_routing_invalid_response_returns_502(client, mock_planner):
    mock_planner.plan.side_effect = RoutingInvalidResponseError("bad json")

    response = client.post(
        URL,
        data={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        content_type="application/json",
    )

    assert response.status_code == 502
    assert "routing service" in response.json()["detail"].lower()


def test_mixed_text_and_coordinates_is_allowed_when_valid(client, mock_planner):
    response = client.post(
        URL,
        data={
            "start": "Dallas, TX",
            "finish": {"latitude": 34.0522, "longitude": -118.2437},
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    mock_planner.plan.assert_called_once()


def test_openapi_schema_includes_fuel_plan_endpoint(client):
    response = client.get(
        "/api/schema/",
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )
    assert response.status_code == 200
    schema = json.loads(response.content)
    assert "/api/v1/routes/fuel-plan/" in schema["paths"]


# --- Health ---


def test_django_settings_load():
    from django.conf import settings

    assert settings.configured
    assert "route_planner" in settings.INSTALLED_APPS


def test_health_endpoint_returns_200(client):
    response = client.get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Demo verification page ---


def test_fuel_plan_demo_page_loads(client):
    from django.urls import reverse

    response = client.get(reverse("fuel-plan-demo"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Demo / manual verification UI" in content
    assert reverse("fuel-plan") in content


# --- Performance: ORS call counts (mocked HTTP) ---


from decimal import Decimal as _Decimal
from unittest.mock import MagicMock as _MagicMock

import pytest as _pytest
from django.contrib.gis.geos import Point as _Point
from django.core.cache import cache as _cache

from route_planner.models import FuelStation as _FuelStation
from route_planner.services.route_planner import RoutePlanner as _RoutePlanner
from route_planner.services.routing.open_route_service import (
    OpenRouteServiceProvider as _OpenRouteServiceProvider,
)
from route_planner.tests.test_open_route_service import _response as _ors_response

_CACHE_ROUTE_GEOMETRY = {
    "type": "LineString",
    "coordinates": [[-105.0, 39.0], [-104.0, 39.0]],
}
_CACHE_ROUTE_DISTANCE_MILES = 600.0
_CACHE_ROUTE_DISTANCE_METERS = _CACHE_ROUTE_DISTANCE_MILES / 0.000621371
_CACHE_START_LAT, _CACHE_START_LON = 39.0, -105.0
_CACHE_FINISH_LAT, _CACHE_FINISH_LON = 39.0, -104.0


@_pytest.fixture
def _clear_routing_cache():
    _cache.clear()
    yield
    _cache.clear()


@_pytest.fixture
def _mock_routing_provider():
    session = _MagicMock()

    def handler(*, method, url, params=None, **kwargs):
        if method == "GET" and "pelias" in url:
            text = (params or {}).get("text", "").casefold()
            if "finish" in text:
                coordinates = [_CACHE_FINISH_LON, _CACHE_FINISH_LAT]
                label = "Finish, CO, USA"
            else:
                coordinates = [_CACHE_START_LON, _CACHE_START_LAT]
                label = "Start, CO, USA"
            return _ors_response(
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
            return _ors_response(
                200,
                {
                    "features": [
                        {
                            "geometry": _CACHE_ROUTE_GEOMETRY,
                            "properties": {
                                "summary": {
                                    "distance": _CACHE_ROUTE_DISTANCE_METERS,
                                    "duration": 36000.0,
                                }
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request {method} {url}")

    session.request.side_effect = lambda **kwargs: handler(**kwargs)
    provider = _OpenRouteServiceProvider(
        base_url="https://api.heigit.org",
        api_key="test-key",
        geocode_cache_timeout_seconds=3600,
        route_cache_timeout_seconds=3600,
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
        session=session,
    )
    return provider, session


def _provider_http_calls(session):
    geocode = 0
    directions = 0
    for call in session.request.call_args_list:
        kwargs = call.kwargs
        if kwargs.get("method") == "GET" and "pelias" in kwargs.get("url", ""):
            geocode += 1
        if kwargs.get("method") == "POST" and "directions" in kwargs.get("url", ""):
            directions += 1
    return geocode, directions


@_pytest.fixture
def _corridor_station(db):
    return _FuelStation.objects.create(
        opis_truckstop_id="cache-test",
        name="Corridor Stop",
        address="I-40",
        city="Denver",
        state="CO",
        rack_id="1",
        retail_price=_Decimal("3.000000"),
        location=_Point(-104.333333, 39.0, srid=4326),
        geocoding_status=_FuelStation.GeocodingStatus.MATCHED,
        source_line_number=424242,
    )


@_pytest.mark.usefixtures("_clear_routing_cache")
@_pytest.mark.django_db
def test_coordinate_request_one_directions_call_on_miss(client, _mock_routing_provider, _corridor_station):
    provider, session = _mock_routing_provider
    planner = _RoutePlanner(provider)
    payload = {
        "start": {"latitude": _CACHE_START_LAT, "longitude": _CACHE_START_LON},
        "finish": {"latitude": _CACHE_FINISH_LAT, "longitude": _CACHE_FINISH_LON},
    }
    with patch("route_planner.views_fuel_plan.get_route_planner", return_value=planner):
        response = client.post(URL, payload, content_type="application/json")
    assert response.status_code == 200
    _, directions = _provider_http_calls(session)
    assert directions == 1


@_pytest.mark.usefixtures("_clear_routing_cache")
@_pytest.mark.django_db
def test_second_identical_request_adds_zero_provider_calls(
    client, _mock_routing_provider, _corridor_station
):
    provider, session = _mock_routing_provider
    planner = _RoutePlanner(provider)
    payload = {
        "start": {"latitude": _CACHE_START_LAT, "longitude": _CACHE_START_LON},
        "finish": {"latitude": _CACHE_FINISH_LAT, "longitude": _CACHE_FINISH_LON},
    }
    with patch("route_planner.views_fuel_plan.get_route_planner", return_value=planner):
        client.post(URL, payload, content_type="application/json")
        geocode_after_first, directions_after_first = _provider_http_calls(session)
        client.post(URL, payload, content_type="application/json")
        geocode_after_second, directions_after_second = _provider_http_calls(session)

    assert directions_after_first == 1
    assert directions_after_second == 1
    assert geocode_after_second == geocode_after_first


@_pytest.mark.usefixtures("_clear_routing_cache")
@_pytest.mark.django_db
def test_text_request_geocode_and_directions_counts(client, _mock_routing_provider, _corridor_station):
    provider, session = _mock_routing_provider
    planner = _RoutePlanner(provider)
    payload = {"start": "Route start, CO", "finish": "Route finish, CO"}
    with patch("route_planner.views_fuel_plan.get_route_planner", return_value=planner):
        client.post(URL, payload, content_type="application/json")
        client.post(URL, payload, content_type="application/json")
    geocode_calls, directions_calls = _provider_http_calls(session)
    assert geocode_calls == 2
    assert directions_calls == 1


@_pytest.mark.usefixtures("_clear_routing_cache")
@_pytest.mark.django_db
def test_fuel_price_change_with_cached_route(client, _mock_routing_provider, _corridor_station):
    provider, session = _mock_routing_provider
    planner = _RoutePlanner(provider)
    payload = {
        "start": {"latitude": _CACHE_START_LAT, "longitude": _CACHE_START_LON},
        "finish": {"latitude": _CACHE_FINISH_LAT, "longitude": _CACHE_FINISH_LON},
    }
    with patch("route_planner.views_fuel_plan.get_route_planner", return_value=planner):
        first = client.post(URL, payload, content_type="application/json")
        _corridor_station.retail_price = _Decimal("5.000000")
        _corridor_station.save(update_fields=["retail_price", "updated_at"])
        second = client.post(URL, payload, content_type="application/json")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["total_fuel_cost"] != second.json()["total_fuel_cost"]
    _, directions_calls = _provider_http_calls(session)
    assert directions_calls == 1


@_pytest.mark.django_db
def test_routing_provider_server_error_returns_503_via_planner(client):
    routing = create_autospec(RoutingProvider, instance=True)
    routing.geocode_location.return_value = GeocodedLocation(
        latitude=39.0,
        longitude=-105.0,
        formatted_address="Start",
    )
    routing.get_route.side_effect = RoutingServerError("timeout")

    with patch(
        "route_planner.views_fuel_plan.get_route_planner",
        return_value=RoutePlanner(routing),
    ):
        response = client.post(
            URL,
            data={
                "start": {"latitude": 39.0, "longitude": -105.0},
                "finish": {"latitude": 39.0, "longitude": -104.0},
            },
            content_type="application/json",
        )

    assert response.status_code == 503
    routing.get_route.assert_called_once()
