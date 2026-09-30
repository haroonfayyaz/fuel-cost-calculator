"""API tests for POST /api/v1/routes/fuel-plan/."""

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
