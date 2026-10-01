"""
Minimum-cost refueling along a one-dimensional route (mile markers).

The vehicle starts with a full tank (50 gallons at 10 MPG => 500-mile range).
Fuel may only be purchased at candidate stations, ordered by ``route_mile``.

Greedy strategy (at each stop where a purchase is required):

1. If current fuel can reach the destination, buy nothing further.
2. Among stations strictly ahead within ``current_fuel * MPG`` miles, find stations
   priced lower than the current station.
3. If a cheaper station exists, buy the minimum gallons needed to reach the nearest
   such cheaper station (without exceeding tank capacity). If current fuel already
   suffices, drive there directly without purchasing.
4. Otherwise buy the minimum of:
   - gallons needed to reach the destination, or
   - gallons needed to fill the tank (never over-buy for the remainder of the trip).
5. After filling because no cheaper station is reachable, skip ahead to the farthest
   candidate station still reachable on the new fuel level (or finish if the
   destination is reachable).

All monetary values use ``Decimal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

MAX_RANGE_MILES = Decimal("500")
MPG = Decimal("10")
TANK_CAPACITY_GALLONS = Decimal("50")


class RouteNotFeasibleError(Exception):
    """The destination cannot be reached with the given stations and range."""


@dataclass(frozen=True)
class FuelCandidateStation:
    route_mile: Decimal
    price_per_gallon: Decimal
    metadata: Any = None


@dataclass(frozen=True)
class FuelStop:
    station: FuelCandidateStation
    route_mile: Decimal
    price_per_gallon: Decimal
    gallons_before: Decimal
    gallons_purchased: Decimal
    gallons_after: Decimal
    cost: Decimal


@dataclass(frozen=True)
class FuelPlan:
    stops: tuple[FuelStop, ...]
    total_fuel_cost: Decimal
    fuel_purchased_gallons: Decimal
    fuel_consumed_gallons: Decimal
    ending_fuel_gallons: Decimal


def _miles_to_gallons(miles: Decimal) -> Decimal:
    return miles / MPG


def _gallons_to_miles(gallons: Decimal) -> Decimal:
    return gallons * MPG


def _normalize_stations(
    stations: Sequence[FuelCandidateStation],
    route_distance_miles: Decimal,
) -> list[FuelCandidateStation]:
    filtered = [s for s in stations if Decimal("0") < s.route_mile <= route_distance_miles]
    filtered.sort(key=lambda s: (s.route_mile, s.price_per_gallon))
    merged: list[FuelCandidateStation] = []
    for station in filtered:
        if merged and merged[-1].route_mile == station.route_mile:
            if station.price_per_gallon < merged[-1].price_per_gallon:
                merged[-1] = station
        else:
            merged.append(station)
    return merged


def _reachable_stations(
    stations: Sequence[FuelCandidateStation],
    *,
    pos: Decimal,
    fuel: Decimal,
) -> list[FuelCandidateStation]:
    horizon = pos + _gallons_to_miles(fuel)
    return [s for s in stations if pos < s.route_mile <= horizon]


def _cheaper_ahead(
    stations: Sequence[FuelCandidateStation],
    *,
    pos: Decimal,
    fuel: Decimal,
    current_price: Decimal,
) -> list[FuelCandidateStation]:
    horizon = pos + _gallons_to_miles(fuel)
    return [
        s
        for s in stations
        if s.route_mile > pos and s.route_mile <= horizon and s.price_per_gallon < current_price
    ]


def _drive_to(station: FuelCandidateStation, *, pos: Decimal, fuel: Decimal) -> tuple[Decimal, Decimal]:
    segment_miles = station.route_mile - pos
    if segment_miles <= 0:
        raise RouteNotFeasibleError("Cannot drive to a station that is not ahead.")
    fuel -= _miles_to_gallons(segment_miles)
    if fuel < 0:
        raise RouteNotFeasibleError("Fuel level became negative while driving to a station.")
    return station.route_mile, fuel


def _station_at_mile(
    stations: Sequence[FuelCandidateStation],
    mile: Decimal,
) -> FuelCandidateStation | None:
    for station in stations:
        if station.route_mile == mile:
            return station
    return None


def optimize_fuel_plan(
    route_distance_miles: Decimal | float | int,
    candidate_stations: Sequence[FuelCandidateStation],
    *,
    max_range_miles: Decimal = MAX_RANGE_MILES,
    mpg: Decimal = MPG,
    tank_capacity_gallons: Decimal = TANK_CAPACITY_GALLONS,
    starting_fuel_gallons: Decimal = TANK_CAPACITY_GALLONS,
) -> FuelPlan:
    del mpg  # fixed constant for this assessment
    route_distance = (
        route_distance_miles
        if isinstance(route_distance_miles, Decimal)
        else Decimal(str(route_distance_miles))
    )
    if route_distance <= 0:
        raise ValueError("route_distance_miles must be positive.")

    stations = _normalize_stations(candidate_stations, route_distance)
    pos = Decimal("0")
    fuel = starting_fuel_gallons
    stops: list[FuelStop] = []
    total_cost = Decimal("0")
    total_purchased = Decimal("0")

    if _gallons_to_miles(fuel) > max_range_miles:
        raise ValueError("Starting fuel exceeds configured maximum range.")

    while pos < route_distance:
        remaining_miles = route_distance - pos
        if _gallons_to_miles(fuel) >= remaining_miles:
            break

        current_station = _station_at_mile(stations, pos)
        if current_station is None:
            reachable = _reachable_stations(stations, pos=pos, fuel=fuel)
            if not reachable:
                raise RouteNotFeasibleError(
                    f"No reachable fuel station between mile {pos} and mile {route_distance}."
                )
            current_station = min(reachable, key=lambda s: s.route_mile)
            pos, fuel = _drive_to(current_station, pos=pos, fuel=fuel)
            remaining_miles = route_distance - pos
            if _gallons_to_miles(fuel) >= remaining_miles:
                break

        remaining_miles = route_distance - pos
        if _gallons_to_miles(fuel) >= remaining_miles:
            break

        cheaper = _cheaper_ahead(
            stations,
            pos=pos,
            fuel=fuel,
            current_price=current_station.price_per_gallon,
        )
        if cheaper:
            target = min(cheaper, key=lambda s: s.route_mile)
            gallons_needed = _miles_to_gallons(target.route_mile - pos) - fuel
            if gallons_needed <= 0:
                pos, fuel = _drive_to(target, pos=pos, fuel=fuel)
                continue

            gallons_purchased = min(gallons_needed, tank_capacity_gallons - fuel)
            if gallons_purchased <= 0:
                raise RouteNotFeasibleError("Unable to purchase enough fuel to reach a cheaper station.")
            if fuel + gallons_purchased < _miles_to_gallons(target.route_mile - pos):
                raise RouteNotFeasibleError(
                    "Tank capacity is insufficient to reach the next cheaper station."
                )

            gallons_before = fuel
            cost = gallons_purchased * current_station.price_per_gallon
            fuel += gallons_purchased
            total_cost += cost
            total_purchased += gallons_purchased
            stops.append(
                FuelStop(
                    station=current_station,
                    route_mile=current_station.route_mile,
                    price_per_gallon=current_station.price_per_gallon,
                    gallons_before=gallons_before,
                    gallons_purchased=gallons_purchased,
                    gallons_after=fuel,
                    cost=cost,
                )
            )
            pos, fuel = _drive_to(target, pos=pos, fuel=fuel)
            continue

        gallons_to_destination = _miles_to_gallons(remaining_miles)
        gallons_purchased = min(
            tank_capacity_gallons - fuel,
            gallons_to_destination - fuel,
        )
        if gallons_purchased <= 0:
            raise RouteNotFeasibleError("Unable to purchase enough fuel to continue.")

        gallons_before = fuel
        cost = gallons_purchased * current_station.price_per_gallon
        fuel += gallons_purchased
        total_cost += cost
        total_purchased += gallons_purchased
        stops.append(
            FuelStop(
                station=current_station,
                route_mile=current_station.route_mile,
                price_per_gallon=current_station.price_per_gallon,
                gallons_before=gallons_before,
                gallons_purchased=gallons_purchased,
                gallons_after=fuel,
                cost=cost,
            )
        )

        if _gallons_to_miles(fuel) >= remaining_miles:
            break

        horizon = pos + _gallons_to_miles(fuel)
        ahead = [s for s in stations if pos < s.route_mile <= min(horizon, route_distance)]
        if not ahead:
            if _gallons_to_miles(fuel) < remaining_miles:
                raise RouteNotFeasibleError("Insufficient fuel after refueling.")
            break

        farthest = max(ahead, key=lambda s: s.route_mile)
        pos, fuel = _drive_to(farthest, pos=pos, fuel=fuel)

    fuel_consumed = _miles_to_gallons(route_distance)
    ending_fuel = starting_fuel_gallons + total_purchased - fuel_consumed

    if ending_fuel < 0:
        raise RouteNotFeasibleError("Route fuel balance is negative after simulation.")
    if ending_fuel > tank_capacity_gallons:
        raise RouteNotFeasibleError("Ending fuel exceeds tank capacity.")

    return FuelPlan(
        stops=tuple(stops),
        total_fuel_cost=total_cost,
        fuel_purchased_gallons=total_purchased,
        fuel_consumed_gallons=fuel_consumed,
        ending_fuel_gallons=ending_fuel,
    )
