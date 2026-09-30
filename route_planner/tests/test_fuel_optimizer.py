"""Unit tests for pure fuel optimization logic."""

from decimal import Decimal

import pytest

from route_planner.services.fuel_optimizer import (
    MAX_RANGE_MILES,
    MPG,
    TANK_CAPACITY_GALLONS,
    FuelCandidateStation,
    RouteNotFeasibleError,
    optimize_fuel_plan,
)
from route_planner.tests.test_fuel_optimizer_invariants import assert_successful_plan_invariants


def station(mile: float | str, price: float | str, name: str = "S") -> FuelCandidateStation:
    return FuelCandidateStation(
        route_mile=Decimal(str(mile)),
        price_per_gallon=Decimal(str(price)),
        metadata={"name": name},
    )


def assert_plan_invariants(plan, route_distance: Decimal):
    assert plan.fuel_consumed_gallons == route_distance / MPG
    assert plan.ending_fuel_gallons == TANK_CAPACITY_GALLONS + plan.fuel_purchased_gallons - plan.fuel_consumed_gallons
    assert plan.total_fuel_cost == sum((stop.cost for stop in plan.stops), Decimal("0"))
    assert plan.fuel_purchased_gallons == sum(
        (stop.gallons_purchased for stop in plan.stops),
        Decimal("0"),
    )
    for stop in plan.stops:
        assert stop.gallons_before >= 0
        assert stop.gallons_purchased >= 0
        assert stop.gallons_after <= TANK_CAPACITY_GALLONS
        assert stop.gallons_after == stop.gallons_before + stop.gallons_purchased
        assert stop.cost == stop.gallons_purchased * stop.price_per_gallon
        assert stop.gallons_after >= 0


def simulate_segments(route_distance: Decimal, plan, stations: list[FuelCandidateStation]):
    """Verify each travel segment is within range and fuel never negative."""
    stations_by_mile = {s.route_mile: s for s in stations}
    pos = Decimal("0")
    fuel = TANK_CAPACITY_GALLONS
    stop_index = 0

    while pos < route_distance:
        remaining = route_distance - pos
        if _gallons_to_miles(fuel) >= remaining:
            fuel -= remaining / MPG
            pos = route_distance
            break

        reachable = pos + _gallons_to_miles(fuel)
        assert reachable <= pos + MAX_RANGE_MILES + Decimal("0.000001")

        if stop_index < len(plan.stops):
            stop = plan.stops[stop_index]
            target_mile = stop.route_mile
            assert target_mile > pos
            assert target_mile <= reachable
            segment = target_mile - pos
            fuel -= segment / MPG
            pos = target_mile
            assert fuel == stop.gallons_before
            fuel = stop.gallons_after
            stop_index += 1
            continue

        ahead = [s for s in stations if pos < s.route_mile <= reachable]
        assert ahead, "Expected a reachable station or destination completion"
        next_mile = min(s.route_mile for s in ahead)
        fuel -= (next_mile - pos) / MPG
        pos = next_mile

    assert fuel >= 0
    assert fuel <= TANK_CAPACITY_GALLONS
    assert stop_index == len(plan.stops)


def _gallons_to_miles(gallons: Decimal) -> Decimal:
    return gallons * MPG


def test_route_100_miles_no_stops():
    plan = optimize_fuel_plan(Decimal("100"), [])
    assert plan.stops == ()
    assert plan.fuel_purchased_gallons == 0
    assert plan.fuel_consumed_gallons == Decimal("10")
    assert plan.ending_fuel_gallons == Decimal("40")
    assert_plan_invariants(plan, Decimal("100"))
    assert_successful_plan_invariants(plan, Decimal("100"))


def test_route_499_miles_no_stops():
    plan = optimize_fuel_plan(Decimal("499"), [])
    assert plan.stops == ()
    assert plan.fuel_purchased_gallons == 0


def test_route_500_miles_no_stops():
    plan = optimize_fuel_plan(Decimal("500"), [])
    assert plan.stops == ()
    assert plan.fuel_purchased_gallons == 0


def test_route_501_miles_requires_station():
    plan = optimize_fuel_plan(Decimal("501"), [station("400", "3.25")])
    assert len(plan.stops) == 1
    assert plan.stops[0].route_mile == Decimal("400")
    assert plan.fuel_purchased_gallons > 0
    assert_plan_invariants(plan, Decimal("501"))


def test_route_1000_miles_with_two_stops():
    stations = [station("450", "4.00", "A"), station("950", "3.50", "B")]
    plan = optimize_fuel_plan(Decimal("1000"), stations)
    assert len(plan.stops) >= 1
    assert plan.fuel_purchased_gallons > 0
    assert_plan_invariants(plan, Decimal("1000"))
    simulate_segments(Decimal("1000"), plan, stations)


def test_expensive_then_cheaper_buys_minimum_at_expensive():
    stations = [
        station("100", "5.00", "expensive"),
        station("400", "2.00", "cheap"),
    ]
    plan = optimize_fuel_plan(Decimal("600"), stations)
    assert len(plan.stops) >= 1
    assert plan.stops[-1].route_mile == Decimal("400")
    assert plan.total_fuel_cost < Decimal("200")
    assert_plan_invariants(plan, Decimal("600"))


def test_cheaper_station_just_inside_range():
    stations = [
        station("100", "5.00", "expensive"),
        station("500", "2.00", "cheap"),
    ]
    plan = optimize_fuel_plan(Decimal("800"), stations)
    assert not any(stop.route_mile == Decimal("100") for stop in plan.stops)
    assert plan.stops[0].route_mile == Decimal("500")
    assert plan.stops[0].gallons_purchased == Decimal("30")
    assert_plan_invariants(plan, Decimal("800"))


def test_cheaper_station_just_outside_range_fills_instead():
    stations = [
        station("100", "5.00", "expensive"),
        station("520", "2.00", "cheap"),
    ]
    plan = optimize_fuel_plan(Decimal("550"), stations)
    assert plan.stops[0].route_mile == Decimal("100")
    assert plan.stops[0].gallons_purchased == Decimal("5")
    assert all(stop.route_mile != Decimal("520") for stop in plan.stops)
    assert_plan_invariants(plan, Decimal("550"))


def test_no_station_within_range_raises():
    with pytest.raises(RouteNotFeasibleError):
        optimize_fuel_plan(Decimal("700"), [station("100", "3.00")])


def test_no_unnecessary_final_purchase_when_destination_reachable():
    plan = optimize_fuel_plan(Decimal("450"), [station("400", "4.00")])
    assert plan.stops == ()
    assert plan.fuel_purchased_gallons == 0


def test_multiple_stations_same_mile_use_cheapest():
    stations = [
        station("300", "4.00", "high"),
        station("300", "2.50", "low"),
    ]
    plan = optimize_fuel_plan(Decimal("600"), stations)
    assert len(plan.stops) == 1
    assert plan.stops[0].price_per_gallon == Decimal("2.50")
    assert_plan_invariants(plan, Decimal("600"))


def test_decimal_price_calculations():
    plan = optimize_fuel_plan(
        Decimal("501"),
        [station("400", "3.333333")],
    )
    stop = plan.stops[0]
    assert stop.cost == stop.gallons_purchased * Decimal("3.333333")
    assert isinstance(stop.cost, Decimal)
    assert_plan_invariants(plan, Decimal("501"))


def test_fuel_levels_remain_within_bounds():
    stations = [station("250", "3.10"), station("700", "2.90")]
    plan = optimize_fuel_plan(Decimal("900"), stations)
    for stop in plan.stops:
        assert Decimal("0") <= stop.gallons_before <= TANK_CAPACITY_GALLONS
        assert Decimal("0") <= stop.gallons_after <= TANK_CAPACITY_GALLONS
    assert Decimal("0") <= plan.ending_fuel_gallons <= TANK_CAPACITY_GALLONS


def test_total_cost_equals_sum_of_stop_costs():
    plan = optimize_fuel_plan(
        Decimal("1200"),
        [station("400", "3.75"), station("900", "3.25")],
    )
    assert plan.total_fuel_cost == sum((s.cost for s in plan.stops), Decimal("0"))


def test_segment_feasibility_simulation():
    stations = [station("480", "3.00"), station("980", "2.75")]
    route = Decimal("1000")
    plan = optimize_fuel_plan(route, stations)
    simulate_segments(route, plan, stations)
