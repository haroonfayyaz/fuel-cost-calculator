"""Performance and query-shape verification (no live external HTTP)."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from unittest.mock import create_autospec

import pytest
from django.contrib.gis.geos import LineString, Point

from route_planner.models import FuelStation
from route_planner.services.route_planner import RouteLocationInput, RoutePlanner, RoutePlanRequest
from route_planner.services.routing.base import RoutePoint, RouteResult, RoutingProvider
from route_planner.services.station_finder import (
    corridor_station_queryset,
    find_stations_near_route,
    geojson_to_linestring,
)

METERS_PER_MILE = 1609.344


def _straight_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float) -> dict:
    return {
        "type": "LineString",
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
    }


def _route_result(*, geometry: dict, distance_miles: float) -> RouteResult:
    return RouteResult(
        geometry=geometry,
        total_distance_meters=distance_miles / 0.000621371,
        total_distance_miles=distance_miles,
        duration_seconds=3600.0,
    )


def _seed_stations_along_route(
    start: tuple[float, float],
    finish: tuple[float, float],
    *,
    count: int,
    line_number_base: int,
) -> None:
    """Place matched stations on the straight segment (for feasibility in perf tests)."""
    for index in range(count):
        fraction = (index + 1) / (count + 1)
        lon = start[0] + fraction * (finish[0] - start[0])
        lat = start[1] + fraction * (finish[1] - start[1])
        FuelStation.objects.create(
            opis_truckstop_id=f"corridor-{line_number_base + index}",
            name=f"Corridor {index}",
            address=f"Hwy segment {line_number_base + index}",
            city="Route",
            state="CO",
            rack_id="1",
            retail_price=Decimal("3.000000"),
            location=Point(lon, lat, srid=4326),
            geocoding_status=FuelStation.GeocodingStatus.MATCHED,
            source_line_number=line_number_base + index,
        )


@pytest.fixture
def large_station_dataset(db):
    """Spread matched stations across the U.S. (not a full-table scan target for corridor search)."""
    bulk: list[FuelStation] = []
    for index in range(3000):
        lon = -125.0 + (index % 100) * 0.45
        lat = 25.0 + (index // 100) * 0.35
        bulk.append(
            FuelStation(
                opis_truckstop_id=f"bulk-{index}",
                name=f"Bulk {index}",
                address=f"{index} Hwy",
                city="City",
                state="TX" if index % 3 else "CO",
                rack_id="1",
                retail_price=Decimal("3.250000"),
                location=Point(lon, lat, srid=4326),
                geocoding_status=FuelStation.GeocodingStatus.MATCHED,
                source_line_number=10_000 + index,
            )
        )
    FuelStation.objects.bulk_create(bulk, batch_size=500)
    return len(bulk)


@pytest.mark.django_db
def test_corridor_query_sql_uses_postgis_dwithin():
    geometry = _straight_route(-105.0, 39.0, -104.0, 39.0)
    route_ewkt = geojson_to_linestring(geometry).ewkt
    sql = str(corridor_station_queryset(route_ewkt, 5.0 * METERS_PER_MILE).query).upper()
    assert "ST_DWITHIN" in sql
    assert "ST_LINELOCATEPOINT" in sql
    assert "ST_DISTANCE" in sql


@pytest.mark.django_db
def test_corridor_explain_references_spatial_index(large_station_dataset):
    geometry = _straight_route(-109.0, 39.0, -103.0, 39.0)
    route_ewkt = geojson_to_linestring(geometry).ewkt
    queryset = corridor_station_queryset(route_ewkt, 5.0 * METERS_PER_MILE)
    plan = queryset.explain()
    plan_lower = plan.lower()
    assert "st_dwithin" in plan_lower


@pytest.mark.django_db
def test_find_stations_single_query_with_large_table(
    django_assert_num_queries, large_station_dataset
):
    geometry = _straight_route(-105.0, 39.0, -104.0, 39.0)
    with django_assert_num_queries(1):
        candidates = find_stations_near_route(geometry, 54.0, corridor_radius_miles=5.0)
    assert isinstance(candidates, list)


@pytest.mark.django_db
def test_coordinate_plan_one_routing_call_and_one_station_query(
    django_assert_num_queries, large_station_dataset
):
    geometry = _straight_route(-105.0, 39.0, -104.0, 39.0)
    routing = create_autospec(RoutingProvider, instance=True)
    routing.get_route.return_value = _route_result(geometry=geometry, distance_miles=54.0)
    planner = RoutePlanner(routing)

    with django_assert_num_queries(1):
        planner.plan(
            RoutePlanRequest(
                start=RouteLocationInput(latitude=39.0, longitude=-105.0),
                finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
            )
        )

    routing.geocode_location.assert_not_called()
    routing.get_route.assert_called_once()


@pytest.mark.django_db
def test_optimizer_receives_only_corridor_candidates(large_station_dataset):
    geometry = _straight_route(-105.0, 39.0, -104.0, 39.0)
    _seed_stations_along_route((-105.0, 39.0), (-104.0, 39.0), count=3, line_number_base=50_000)
    corridor_count = len(
        find_stations_near_route(geometry, 600.0, corridor_radius_miles=5.0)
    )
    assert corridor_count < large_station_dataset + 3

    routing = create_autospec(RoutingProvider, instance=True)
    routing.get_route.return_value = _route_result(geometry=geometry, distance_miles=600.0)
    planner = RoutePlanner(routing)
    result = planner.plan(
        RoutePlanRequest(
            start=RouteLocationInput(latitude=39.0, longitude=-105.0),
            finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
        )
    )
    assert result.diagnostics.candidate_station_count == corridor_count
    assert result.diagnostics.candidate_station_count < 500


@pytest.mark.django_db
def test_route_plan_emits_structured_timing_log(caplog, large_station_dataset):
    geometry = _straight_route(-105.0, 39.0, -104.0, 39.0)
    routing = create_autospec(RoutingProvider, instance=True)
    routing.get_route.return_value = _route_result(geometry=geometry, distance_miles=100.0)
    planner = RoutePlanner(routing)

    with caplog.at_level(logging.INFO, logger="route_planner.services.route_planner"):
        planner.plan(
            RoutePlanRequest(
                start=RouteLocationInput(latitude=39.0, longitude=-105.0),
                finish=RouteLocationInput(latitude=39.0, longitude=-104.0),
            )
        )

    record = next(r for r in caplog.records if r.getMessage() == "route_plan_completed")
    for field in (
        "geocoding_ms",
        "routing_ms",
        "station_lookup_ms",
        "optimization_ms",
        "total_ms",
        "candidate_station_count",
    ):
        assert hasattr(record, field), field
    assert record.geocoding_ms == pytest.approx(0.0, abs=1.0)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("label", "start", "finish", "distance_miles", "use_bulk_dataset"),
    [
        ("short", (-105.0, 39.0), (-104.95, 39.0), 100.0, True),
        ("medium", (-105.0, 39.0), (-104.0, 39.0), 600.0, True),
        ("cross_country", (-109.0, 39.0), (-103.0, 39.0), 2600.0, False),
    ],
)
def test_benchmark_report(
    label,
    start,
    finish,
    distance_miles,
    use_bulk_dataset,
    django_assert_num_queries,
    request,
):
    if use_bulk_dataset:
        request.getfixturevalue("large_station_dataset")

    geometry = _straight_route(start[0], start[1], finish[0], finish[1])
    routing = create_autospec(RoutingProvider, instance=True)
    routing.get_route.return_value = _route_result(
        geometry=geometry,
        distance_miles=distance_miles,
    )
    planner = RoutePlanner(routing)

    if distance_miles > 500:
        station_count = 30 if distance_miles >= 2000 else 6
        _seed_stations_along_route(
            start, finish, count=station_count, line_number_base=60_000
        )

    query_count = 0

    def _count_queries(execute, sql, params, many, context):
        nonlocal query_count
        query_count += 1
        return execute(sql, params, many, context)

    from django.db import connection

    with connection.execute_wrapper(_count_queries):
        started = time.perf_counter()
        result = planner.plan(
            RoutePlanRequest(
                start=RouteLocationInput(latitude=start[1], longitude=start[0]),
                finish=RouteLocationInput(latitude=finish[1], longitude=finish[0]),
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

    assert routing.get_route.call_count == 1
    assert query_count == 1
    if use_bulk_dataset:
        assert result.diagnostics.candidate_station_count < 3000

    print(
        f"\n[benchmark:{label}] candidates={result.diagnostics.candidate_station_count} "
        f"db_queries={query_count} provider_calls=1 wall_ms={elapsed_ms:.2f}"
    )
