"""
Orchestrates geocoding, routing, corridor station search, and fuel optimization.

Views should call ``RoutePlanner`` only; business rules live here and in downstream services.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from django.conf import settings

logger = logging.getLogger(__name__)

from route_planner.services.fuel_optimizer import (
    FuelCandidateStation,
    RouteNotFeasibleError,
    optimize_fuel_plan,
)
from route_planner.services.routing.base import (
    RoutePoint,
    RoutingProvider,
)
from route_planner.services.station_finder import (
    CandidateFuelStation,
    find_stations_near_route,
)


class RoutePlannerValidationError(ValueError):
    """Invalid start, finish, or request parameters."""


class RoutePlanNotFeasibleError(Exception):
    """The route cannot be completed with available fuel stops and vehicle range."""


# Approximate U.S. bounds (continental + Alaska + Hawaii + Puerto Rico envelope).
_USA_LAT_MIN = 17.5
_USA_LAT_MAX = 72.0
_USA_LON_MIN = -180.0
_USA_LON_MAX = -65.0


@dataclass(frozen=True)
class RouteLocationInput:
    """Exactly one of ``text`` or ``(latitude, longitude)`` must be supplied."""

    text: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class RoutePlanRequest:
    start: RouteLocationInput
    finish: RouteLocationInput


@dataclass(frozen=True)
class ResolvedRouteEndpoint:
    latitude: float
    longitude: float
    label: str


@dataclass(frozen=True)
class RouteSummary:
    geometry: dict[str, Any]
    distance_miles: float
    duration_seconds: float


@dataclass(frozen=True)
class VehicleProfile:
    mpg: int
    maximum_range_miles: int
    tank_capacity_gallons: Decimal


@dataclass(frozen=True)
class RoutePlanAssumptions:
    starts_with_full_tank: bool = True
    starting_fuel_cost_included: bool = False


@dataclass(frozen=True)
class PlannedFuelStop:
    station_id: int
    name: str
    address: str
    latitude: float
    longitude: float
    route_mile: Decimal
    price_per_gallon: Decimal
    gallons_before: Decimal
    gallons_purchased: Decimal
    gallons_after: Decimal
    cost: Decimal


@dataclass(frozen=True)
class RoutePlanDiagnostics:
    candidate_station_count: int


@dataclass(frozen=True)
class RoutePlanResult:
    route: RouteSummary
    vehicle: VehicleProfile
    fuel_stops: tuple[PlannedFuelStop, ...]
    fuel_consumed_gallons: Decimal
    fuel_purchased_gallons: Decimal
    total_fuel_cost: Decimal
    assumptions: RoutePlanAssumptions
    diagnostics: RoutePlanDiagnostics


@runtime_checkable
class StationFinder(Protocol):
    def find_stations_along_route(
        self,
        route_geometry: dict[str, Any],
        route_distance_miles: float,
    ) -> list[CandidateFuelStation]:
        """Return fuel stations near the route polyline, ordered along-route."""


class DefaultStationFinder:
    """PostGIS-backed station search (single query, no per-station routing)."""

    def find_stations_along_route(
        self,
        route_geometry: dict[str, Any],
        route_distance_miles: float,
    ) -> list[CandidateFuelStation]:
        return find_stations_near_route(route_geometry, route_distance_miles)


def _validate_endpoint(name: str, location: RouteLocationInput) -> None:
    has_text = location.text is not None and location.text.strip() != ""
    has_coordinates = location.latitude is not None or location.longitude is not None

    if has_text and has_coordinates:
        raise RoutePlannerValidationError(f"{name} must use either text or coordinates, not both.")
    if not has_text and location.latitude is None and location.longitude is None:
        raise RoutePlannerValidationError(f"{name} requires text or coordinates.")
    if location.latitude is not None and location.longitude is None:
        raise RoutePlannerValidationError(f"{name} longitude is required when latitude is set.")
    if location.longitude is not None and location.latitude is None:
        raise RoutePlannerValidationError(f"{name} latitude is required when longitude is set.")

    if has_coordinates:
        assert location.latitude is not None and location.longitude is not None
        lat, lon = location.latitude, location.longitude
        if not (-90.0 <= lat <= 90.0):
            raise RoutePlannerValidationError(f"{name} latitude must be between -90 and 90.")
        if not (-180.0 <= lon <= 180.0):
            raise RoutePlannerValidationError(f"{name} longitude must be between -180 and 180.")
        if not is_usa_coordinate(lat, lon):
            raise RoutePlannerValidationError(f"{name} must be within the United States.")


def is_usa_coordinate(latitude: float, longitude: float) -> bool:
    """Reject coordinates clearly outside U.S. territories (no reverse geocode)."""
    return (
        _USA_LAT_MIN <= latitude <= _USA_LAT_MAX
        and _USA_LON_MIN <= longitude <= _USA_LON_MAX
    )


def _resolve_endpoint(
    name: str,
    location: RouteLocationInput,
    routing_provider: RoutingProvider,
) -> ResolvedRouteEndpoint:
    _validate_endpoint(name, location)

    if location.text is not None and location.text.strip():
        geocoded = routing_provider.geocode_location(location.text.strip())
        return ResolvedRouteEndpoint(
            latitude=geocoded.latitude,
            longitude=geocoded.longitude,
            label=geocoded.formatted_address,
        )

    assert location.latitude is not None and location.longitude is not None
    lat, lon = location.latitude, location.longitude
    return ResolvedRouteEndpoint(
        latitude=lat,
        longitude=lon,
        label=f"{lat:.6f},{lon:.6f}",
    )


def _vehicle_profile() -> VehicleProfile:
    mpg = int(settings.VEHICLE_MPG)
    maximum_range_miles = int(settings.VEHICLE_MAX_RANGE_MILES)
    tank_capacity_gallons = Decimal(maximum_range_miles) / Decimal(mpg)
    return VehicleProfile(
        mpg=mpg,
        maximum_range_miles=maximum_range_miles,
        tank_capacity_gallons=tank_capacity_gallons,
    )


def _candidate_to_optimizer_station(candidate: CandidateFuelStation) -> FuelCandidateStation:
    return FuelCandidateStation(
        route_mile=Decimal(str(candidate.route_mile)),
        price_per_gallon=candidate.retail_price,
        metadata=candidate,
    )


def _build_planned_stop(stop) -> PlannedFuelStop:
    candidate: CandidateFuelStation = stop.station.metadata
    return PlannedFuelStop(
        station_id=candidate.station_id,
        name=candidate.name,
        address=candidate.address,
        latitude=candidate.latitude,
        longitude=candidate.longitude,
        route_mile=stop.route_mile,
        price_per_gallon=stop.price_per_gallon,
        gallons_before=stop.gallons_before,
        gallons_purchased=stop.gallons_purchased,
        gallons_after=stop.gallons_after,
        cost=stop.cost,
    )


class RoutePlanner:
    def __init__(
        self,
        routing_provider: RoutingProvider,
        station_finder: StationFinder | None = None,
    ) -> None:
        self._routing = routing_provider
        self._station_finder = station_finder or DefaultStationFinder()

    def plan(self, request: RoutePlanRequest) -> RoutePlanResult:
        plan_started = time.perf_counter()
        geocoding_ms = 0.0

        _validate_endpoint("start", request.start)
        _validate_endpoint("finish", request.finish)

        geocode_started = time.perf_counter()
        start = _resolve_endpoint("start", request.start, self._routing)
        geocoding_ms += (time.perf_counter() - geocode_started) * 1000

        geocode_started = time.perf_counter()
        finish = _resolve_endpoint("finish", request.finish, self._routing)
        geocoding_ms += (time.perf_counter() - geocode_started) * 1000

        if (
            abs(start.latitude - finish.latitude) < 1e-9
            and abs(start.longitude - finish.longitude) < 1e-9
        ):
            raise RoutePlannerValidationError("start and finish must not be the same location.")

        routing_started = time.perf_counter()
        route = self._routing.get_route(
            RoutePoint(latitude=start.latitude, longitude=start.longitude),
            RoutePoint(latitude=finish.latitude, longitude=finish.longitude),
        )
        routing_ms = (time.perf_counter() - routing_started) * 1000

        if route.total_distance_miles <= 0:
            raise RoutePlannerValidationError("Route distance must be positive.")

        station_lookup_started = time.perf_counter()
        candidates = self._station_finder.find_stations_along_route(
            route.geometry,
            route.total_distance_miles,
        )
        station_lookup_ms = (time.perf_counter() - station_lookup_started) * 1000

        vehicle = _vehicle_profile()
        optimizer_stations = [_candidate_to_optimizer_station(c) for c in candidates]

        optimization_started = time.perf_counter()
        try:
            fuel_plan = optimize_fuel_plan(
                route.total_distance_miles,
                optimizer_stations,
                max_range_miles=Decimal(vehicle.maximum_range_miles),
                tank_capacity_gallons=vehicle.tank_capacity_gallons,
                starting_fuel_gallons=vehicle.tank_capacity_gallons,
            )
        except RouteNotFeasibleError as exc:
            raise RoutePlanNotFeasibleError(str(exc)) from exc
        optimization_ms = (time.perf_counter() - optimization_started) * 1000

        fuel_stops = tuple(_build_planned_stop(stop) for stop in fuel_plan.stops)

        total_ms = (time.perf_counter() - plan_started) * 1000
        logger.info(
            "route_plan_completed",
            extra={
                "geocoding_ms": round(geocoding_ms, 2),
                "routing_ms": round(routing_ms, 2),
                "station_lookup_ms": round(station_lookup_ms, 2),
                "optimization_ms": round(optimization_ms, 2),
                "total_ms": round(total_ms, 2),
                "candidate_station_count": len(candidates),
                "route_distance_miles": round(route.total_distance_miles, 2),
                "fuel_stop_count": len(fuel_stops),
            },
        )

        return RoutePlanResult(
            route=RouteSummary(
                geometry=route.geometry,
                distance_miles=route.total_distance_miles,
                duration_seconds=route.duration_seconds,
            ),
            vehicle=vehicle,
            fuel_stops=fuel_stops,
            fuel_consumed_gallons=fuel_plan.fuel_consumed_gallons,
            fuel_purchased_gallons=fuel_plan.fuel_purchased_gallons,
            total_fuel_cost=fuel_plan.total_fuel_cost,
            assumptions=RoutePlanAssumptions(),
            diagnostics=RoutePlanDiagnostics(candidate_station_count=len(candidates)),
        )
