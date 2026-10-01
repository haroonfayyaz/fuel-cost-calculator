"""Unit tests for pure fuel optimization logic."""

import random
from decimal import Decimal

import pytest

from route_planner.services.fuel_optimizer import (
    MAX_RANGE_MILES,
    MPG,
    TANK_CAPACITY_GALLONS,
    FuelCandidateStation,
    FuelPlan,
    RouteNotFeasibleError,
    optimize_fuel_plan,
)


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


def test_float_route_distance_from_routing_provider():
    """ORS returns float miles; Decimal(float) must not break fuel balance."""
    ors_like_miles = 1442.6752650165001
    stations = [
        station("400", "3.50"),
        station("900", "3.25"),
        station("1200", "3.00"),
    ]
    plan = optimize_fuel_plan(ors_like_miles, stations)
    assert plan.stops
    assert plan.ending_fuel_gallons >= 0


def test_segment_feasibility_simulation():
    stations = [station("480", "3.00"), station("980", "2.75")]
    route = Decimal("1000")
    plan = optimize_fuel_plan(route, stations)
    simulate_segments(route, plan, stations)


def _miles_to_gallons(miles: Decimal) -> Decimal:
    return miles / MPG


def _gallons_to_miles(gallons: Decimal) -> Decimal:
    return gallons * MPG


def assert_successful_plan_invariants(
    plan: FuelPlan,
    route_distance: Decimal,
    *,
    starting_fuel: Decimal = TANK_CAPACITY_GALLONS,
) -> None:
    assert plan.fuel_consumed_gallons == route_distance / MPG
    assert plan.fuel_purchased_gallons == sum(
        (stop.gallons_purchased for stop in plan.stops),
        Decimal("0"),
    )
    assert plan.total_fuel_cost == sum((stop.cost for stop in plan.stops), Decimal("0"))
    assert plan.ending_fuel_gallons == starting_fuel + plan.fuel_purchased_gallons - plan.fuel_consumed_gallons

    previous_mile = Decimal("-1")
    for stop in plan.stops:
        assert stop.gallons_purchased >= 0
        assert stop.route_mile > previous_mile
        assert stop.route_mile <= route_distance
        previous_mile = stop.route_mile
        assert stop.gallons_before >= 0
        assert stop.gallons_after <= TANK_CAPACITY_GALLONS
        assert stop.gallons_after == stop.gallons_before + stop.gallons_purchased
        assert stop.cost == stop.gallons_purchased * stop.price_per_gallon

    pos = Decimal("0")
    fuel = starting_fuel
    stop_index = 0
    while pos < route_distance:
        remaining = route_distance - pos
        if _gallons_to_miles(fuel) >= remaining:
            assert stop_index == len(plan.stops)
            fuel -= _miles_to_gallons(remaining)
            pos = route_distance
            break
        assert stop_index < len(plan.stops)
        stop = plan.stops[stop_index]
        segment_miles = stop.route_mile - pos
        assert segment_miles > 0
        assert segment_miles <= _gallons_to_miles(fuel) + Decimal("0.0000001")
        assert segment_miles <= MAX_RANGE_MILES + Decimal("0.0000001")
        fuel -= _miles_to_gallons(segment_miles)
        pos = stop.route_mile
        assert stop.gallons_before == fuel
        assert Decimal("0") <= fuel <= TANK_CAPACITY_GALLONS
        fuel = stop.gallons_after
        assert Decimal("0") <= fuel <= TANK_CAPACITY_GALLONS
        stop_index += 1
    assert pos == route_distance
    assert Decimal("0") <= fuel <= TANK_CAPACITY_GALLONS
    assert fuel == plan.ending_fuel_gallons


@pytest.mark.parametrize("distance", [Decimal("499.9"), Decimal("500"), Decimal("500.001")])
def test_boundary_around_500_mile_range(distance):
    stations = [station("400", "3.00")] if distance > Decimal("500") else []
    plan = optimize_fuel_plan(distance, stations)
    assert_successful_plan_invariants(plan, distance)
    if distance <= Decimal("500"):
        assert plan.stops == ()
    else:
        assert len(plan.stops) >= 1


def test_same_price_is_not_treated_as_cheaper():
    stations = [station("200", "3.00"), station("400", "3.00")]
    plan = optimize_fuel_plan(Decimal("700"), stations)
    assert_successful_plan_invariants(plan, Decimal("700"))


def test_station_behind_current_position_is_ignored():
    stations = [station("100", "5.00"), station("150", "2.00"), station("600", "2.00")]
    plan = optimize_fuel_plan(Decimal("800"), stations)
    assert all(stop.route_mile >= Decimal("100") for stop in plan.stops)
    assert_successful_plan_invariants(plan, Decimal("800"))


def test_station_at_destination_does_not_force_purchase():
    plan = optimize_fuel_plan(Decimal("500"), [station("500", "9.99")])
    assert plan.stops == ()
    assert_successful_plan_invariants(plan, Decimal("500"))


def test_same_route_mile_keeps_cheapest_only():
    stations = [station("300", "4.00", "high"), station("300", "2.50", "low")]
    plan = optimize_fuel_plan(Decimal("600"), stations)
    assert len(plan.stops) == 1
    assert plan.stops[0].price_per_gallon == Decimal("2.50")
    assert_successful_plan_invariants(plan, Decimal("600"))


def test_skip_ahead_after_fill_preserves_invariants():
    stations = [station("480", "3.00"), station("980", "2.75")]
    plan = optimize_fuel_plan(Decimal("1000"), stations)
    assert_successful_plan_invariants(plan, Decimal("1000"))


def test_fractional_route_distance_and_gallons():
    plan = optimize_fuel_plan(Decimal("501.5"), [station("400", "2.555555")])
    assert_successful_plan_invariants(plan, Decimal("501.5"))
    assert plan.fuel_consumed_gallons == Decimal("501.5") / MPG


def test_cannot_reach_cheaper_when_tank_too_small_raises():
    stations = [station("100", "9.00"), station("650", "1.00")]
    with pytest.raises(RouteNotFeasibleError):
        optimize_fuel_plan(Decimal("700"), stations)


def test_unreachable_gap_raises():
    with pytest.raises(RouteNotFeasibleError):
        optimize_fuel_plan(Decimal("900"), [station("100", "3.00")])


def test_randomized_small_scenarios():
    random.seed(42)
    for _ in range(200):
        route = Decimal(str(random.randint(50, 1200)))
        count = random.randint(0, 8)
        stations: list[FuelCandidateStation] = []
        for index in range(count):
            mile = Decimal(str(random.randint(1, int(route))))
            price = Decimal(str(random.randint(200, 500))) / Decimal("100")
            stations.append(station(mile, price, name=f"S{index}"))
        try:
            plan = optimize_fuel_plan(route, stations)
        except RouteNotFeasibleError:
            continue
        assert_successful_plan_invariants(plan, route)
