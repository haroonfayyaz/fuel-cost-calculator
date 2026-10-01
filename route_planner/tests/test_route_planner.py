"""Orchestration tests for RoutePlanner (mocked routing + station search)."""

from decimal import Decimal
from unittest.mock import MagicMock, create_autospec

import pytest

from route_planner.services.fuel_optimizer import MPG, TANK_CAPACITY_GALLONS
from route_planner.services.route_planner import (
    RouteLocationInput,
    RoutePlanNotFeasibleError,
    RoutePlanner,
    RoutePlannerValidationError,
    RoutePlanRequest,
)
from route_planner.services.routing.base import GeocodedLocation, RoutePoint, RouteResult, RoutingProvider
from route_planner.services.station_finder import CandidateFuelStation


ROUTE_GEOMETRY = {
    "type": "LineString",
    "coordinates": [[-105.0, 39.0], [-104.0, 39.0]],
}


def _route_result(*, distance_miles: float) -> RouteResult:
    return RouteResult(
        geometry=ROUTE_GEOMETRY,
        total_distance_meters=distance_miles / 0.000621371,
        total_distance_miles=distance_miles,
        duration_seconds=3600.0,
    )


def _candidate(
    station_id: int,
    route_mile: float,
    price: str = "3.50",
) -> CandidateFuelStation:
    return CandidateFuelStation(
        station_id=station_id,
        name=f"Station {station_id}",
        address=f"{station_id} Main St",
        latitude=39.0,
        longitude=-104.5,
        retail_price=Decimal(price),
        route_fraction=route_mile / 600.0,
        route_mile=route_mile,
        distance_from_route_miles=0.5,
    )


@pytest.fixture
def routing_provider() -> MagicMock:
    provider = create_autospec(RoutingProvider, instance=True)
    provider.get_route.return_value = _route_result(distance_miles=600.0)
    provider.geocode_location.side_effect = lambda text: GeocodedLocation(
        latitude=39.0,
        longitude=-105.0 if "start" in text.casefold() else -104.0,
        formatted_address=text,
    )
    return provider


@pytest.fixture
def station_finder() -> MagicMock:
    finder = MagicMock()
    finder.find_stations_along_route.return_value = [
        _candidate(1, route_mile=400.0, price="3.00"),
    ]
    return finder


def test_plan_with_coordinates_calls_routing_once(routing_provider, station_finder):
    planner = RoutePlanner(routing_provider, station_finder=station_finder)

    result = planner.plan(
        RoutePlanRequest(
            start=RouteLocationInput(latitude=39.0, longitude=-105.0),
            finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
        )
    )

    routing_provider.geocode_location.assert_not_called()
    routing_provider.get_route.assert_called_once_with(
        RoutePoint(latitude=39.0, longitude=-105.0),
        RoutePoint(latitude=39.0, longitude=-104.0),
    )
    station_finder.find_stations_along_route.assert_called_once_with(
        ROUTE_GEOMETRY,
        600.0,
    )
    assert result.diagnostics.candidate_station_count == 1
    assert result.assumptions.starts_with_full_tank is True
    assert result.assumptions.starting_fuel_cost_included is False
    assert result.route.geometry == ROUTE_GEOMETRY
    assert result.route.distance_miles == 600.0
    assert result.vehicle.mpg == 10
    assert result.vehicle.maximum_range_miles == 500
    assert result.vehicle.tank_capacity_gallons == TANK_CAPACITY_GALLONS
    assert result.fuel_consumed_gallons == Decimal("600") / MPG
    assert result.total_fuel_cost >= Decimal("0")


def test_plan_with_text_geocodes_endpoints_not_stations(routing_provider, station_finder):
    planner = RoutePlanner(routing_provider, station_finder=station_finder)

    planner.plan(
        RoutePlanRequest(
            start=RouteLocationInput(text="Start City, CO"),
            finish=RouteLocationInput(text="Finish City, CO"),
        )
    )

    assert routing_provider.geocode_location.call_count == 2
    routing_provider.get_route.assert_called_once()
    station_finder.find_stations_along_route.assert_called_once()


def test_short_route_no_fuel_stops_uses_real_optimizer(routing_provider, station_finder):
    routing_provider.get_route.return_value = _route_result(distance_miles=100.0)
    station_finder.find_stations_along_route.return_value = []
    planner = RoutePlanner(routing_provider, station_finder=station_finder)

    result = planner.plan(
        RoutePlanRequest(
            start=RouteLocationInput(latitude=39.0, longitude=-105.0),
            finish=RouteLocationInput(latitude=39.0, longitude=-104.9),
        )
    )

    assert result.fuel_stops == ()
    assert result.fuel_purchased_gallons == Decimal("0")
    assert result.fuel_consumed_gallons == Decimal("10")
    routing_provider.get_route.assert_called_once()


def test_unreachable_route_raises_without_extra_routing_calls(routing_provider, station_finder):
    routing_provider.get_route.return_value = _route_result(distance_miles=900.0)
    station_finder.find_stations_along_route.return_value = [
        _candidate(1, route_mile=100.0),
    ]
    planner = RoutePlanner(routing_provider, station_finder=station_finder)

    with pytest.raises(RoutePlanNotFeasibleError):
        planner.plan(
            RoutePlanRequest(
                start=RouteLocationInput(latitude=39.0, longitude=-105.0),
                finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
            )
        )

    routing_provider.get_route.assert_called_once()
    routing_provider.geocode_location.assert_not_called()


def test_rejects_non_us_coordinates():
    planner = RoutePlanner(create_autospec(RoutingProvider, instance=True))

    with pytest.raises(RoutePlannerValidationError, match="United States"):
        planner.plan(
            RoutePlanRequest(
                start=RouteLocationInput(latitude=51.5, longitude=0.1),
                finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
            )
        )


def test_rejects_both_text_and_coordinates():
    planner = RoutePlanner(create_autospec(RoutingProvider, instance=True))

    with pytest.raises(RoutePlannerValidationError, match="either text or coordinates"):
        planner.plan(
            RoutePlanRequest(
                start=RouteLocationInput(text="Denver", latitude=39.0, longitude=-105.0),
                finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
            )
        )


def test_fuel_stop_fields_populated_from_candidates(routing_provider, station_finder):
    planner = RoutePlanner(routing_provider, station_finder=station_finder)

    result = planner.plan(
        RoutePlanRequest(
            start=RouteLocationInput(latitude=39.0, longitude=-105.0),
            finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
        )
    )

    assert len(result.fuel_stops) >= 1
    stop = result.fuel_stops[0]
    assert stop.station_id == 1
    assert stop.name == "Station 1"
    assert stop.gallons_purchased > 0
    assert stop.cost == stop.gallons_purchased * stop.price_per_gallon


def test_plan_never_calls_get_route_per_candidate_station(routing_provider, station_finder):
    station_finder.find_stations_along_route.return_value = [
        _candidate(station_id, route_mile=150.0 + station_id * 40.0)
        for station_id in range(1, 9)
    ]
    planner = RoutePlanner(routing_provider, station_finder=station_finder)

    planner.plan(
        RoutePlanRequest(
            start=RouteLocationInput(latitude=39.0, longitude=-105.0),
            finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
        )
    )

    routing_provider.get_route.assert_called_once()
    assert routing_provider.geocode_location.call_count == 0
