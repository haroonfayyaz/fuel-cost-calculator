"""Invariant verification and adversarial tests for fuel optimization."""

from decimal import Decimal
import random

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


def station(mile, price, name="S") -> FuelCandidateStation:
    return FuelCandidateStation(
        route_mile=Decimal(str(mile)),
        price_per_gallon=Decimal(str(price)),
        metadata={"name": name},
    )


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
    """Assert the 10 required invariants for a successful plan."""
    # 8. Total consumption identity
    assert plan.fuel_consumed_gallons == route_distance / MPG

    # 6 & 7. Aggregates match stop rows
    assert plan.fuel_purchased_gallons == sum(
        (stop.gallons_purchased for stop in plan.stops),
        Decimal("0"),
    )
    assert plan.total_fuel_cost == sum((stop.cost for stop in plan.stops), Decimal("0"))

    # Ending fuel accounting
    assert plan.ending_fuel_gallons == starting_fuel + plan.fuel_purchased_gallons - plan.fuel_consumed_gallons

    # 3 & 4 & 5. Stop ordering and bounds
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

    # Simulate execution: 1, 2, 9, 10
    pos = Decimal("0")
    fuel = starting_fuel
    stop_index = 0

    while pos < route_distance:
        remaining = route_distance - pos
        if _gallons_to_miles(fuel) >= remaining:
            # 9. No further purchases once destination is reachable
            assert stop_index == len(plan.stops)
            fuel -= _miles_to_gallons(remaining)
            pos = route_distance
            break

        assert stop_index < len(plan.stops), "Plan ended before destination but purchases remain unused."
        stop = plan.stops[stop_index]
        segment_miles = stop.route_mile - pos
        assert segment_miles > 0

        # 2 & 10. Segment feasibility and max range
        assert segment_miles <= _gallons_to_miles(fuel) + Decimal("0.0000001")
        assert segment_miles <= MAX_RANGE_MILES + Decimal("0.0000001")

        fuel -= _miles_to_gallons(segment_miles)
        pos = stop.route_mile

        # 1. Fuel bounds at purchase point
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
    stations = [
        station("300", "4.00", "high"),
        station("300", "2.50", "low"),
    ]
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
    stations = [
        station("0.1", "9.00"),  # filtered: must be >0
    ]
    # Craft scenario: expensive early, cheaper very far requiring more than one tank increment
    stations = [
        station("100", "9.00"),
        station("650", "1.00"),
    ]
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
