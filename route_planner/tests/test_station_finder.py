"""PostGIS integration tests for route corridor station search."""

from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point

from route_planner.models import FuelStation
from route_planner.services.station_finder import find_stations_near_route

# Straight east-west segment in Colorado (~1° lon ≈ 54 statute miles at 39°N).
ROUTE_LAT = 39.0
ROUTE_START_LON = -105.0
ROUTE_END_LON = -104.0
ROUTE_DISTANCE_MILES = 54.0
CORRIDOR_MILES = 5.0


def _miles_north(miles: float) -> float:
    return miles / 69.0


def _straight_route_geometry() -> dict:
    return {
        "type": "LineString",
        "coordinates": [
            [ROUTE_START_LON, ROUTE_LAT],
            [ROUTE_END_LON, ROUTE_LAT],
        ],
    }


@pytest.fixture
def synthetic_stations(db):
    def make_station(
        name: str,
        lon: float,
        lat: float,
        *,
        line_number: int,
        geocoded: bool = True,
    ) -> FuelStation:
        kwargs = {
            "opis_truckstop_id": str(line_number),
            "name": name,
            "address": f"{name} address",
            "city": "Denver",
            "state": "CO",
            "rack_id": "1",
            "retail_price": Decimal("3.500000"),
            "source_line_number": line_number,
        }
        if geocoded:
            kwargs["location"] = Point(lon, lat, srid=4326)
            kwargs["geocoding_status"] = FuelStation.GeocodingStatus.MATCHED
        else:
            kwargs["geocoding_status"] = FuelStation.GeocodingStatus.PENDING
        return FuelStation.objects.create(**kwargs)

    mid_lon = (ROUTE_START_LON + ROUTE_END_LON) / 2
    stations = {
        "on_route": make_station("On Route", mid_lon, ROUTE_LAT, line_number=1001),
        "two_miles": make_station(
            "Two Miles",
            mid_lon,
            ROUTE_LAT + _miles_north(2),
            line_number=1002,
        ),
        "four_miles": make_station(
            "Four Miles",
            mid_lon,
            ROUTE_LAT + _miles_north(4),
            line_number=1003,
        ),
        "six_miles": make_station(
            "Six Miles",
            mid_lon,
            ROUTE_LAT + _miles_north(6),
            line_number=1004,
        ),
        "before_start": make_station(
            "Before Start",
            ROUTE_START_LON - 0.5,
            ROUTE_LAT,
            line_number=1005,
        ),
        "after_finish": make_station(
            "After Finish",
            ROUTE_END_LON + 0.5,
            ROUTE_LAT,
            line_number=1006,
        ),
        "early": make_station(
            "Early",
            ROUTE_START_LON + 0.1,
            ROUTE_LAT,
            line_number=1007,
        ),
        "late": make_station(
            "Late",
            ROUTE_END_LON - 0.1,
            ROUTE_LAT,
            line_number=1008,
        ),
        "not_geocoded": make_station(
            "Not Geocoded",
            mid_lon,
            ROUTE_LAT,
            line_number=1009,
            geocoded=False,
        ),
    }
    return stations


@pytest.mark.django_db
def test_corridor_filtering_excludes_distant_and_off_route_stations(synthetic_stations):
    results = find_stations_near_route(
        _straight_route_geometry(),
        ROUTE_DISTANCE_MILES,
        corridor_radius_miles=CORRIDOR_MILES,
    )
    ids = {candidate.station_id for candidate in results}

    assert synthetic_stations["on_route"].pk in ids
    assert synthetic_stations["two_miles"].pk in ids
    assert synthetic_stations["four_miles"].pk in ids
    assert synthetic_stations["six_miles"].pk not in ids
    assert synthetic_stations["before_start"].pk not in ids
    assert synthetic_stations["after_finish"].pk not in ids
    assert synthetic_stations["not_geocoded"].pk not in ids


@pytest.mark.django_db
def test_candidates_sorted_by_route_position(synthetic_stations):
    results = find_stations_near_route(
        _straight_route_geometry(),
        ROUTE_DISTANCE_MILES,
        corridor_radius_miles=CORRIDOR_MILES,
    )
    ordered_ids = [candidate.station_id for candidate in results]
    assert ordered_ids.index(synthetic_stations["early"].pk) < ordered_ids.index(
        synthetic_stations["on_route"].pk
    )
    assert ordered_ids.index(synthetic_stations["on_route"].pk) < ordered_ids.index(
        synthetic_stations["late"].pk
    )


@pytest.mark.django_db
def test_route_mile_increases_monotonically(synthetic_stations):
    results = find_stations_near_route(
        _straight_route_geometry(),
        ROUTE_DISTANCE_MILES,
        corridor_radius_miles=CORRIDOR_MILES,
    )
    route_miles = [candidate.route_mile for candidate in results]
    assert route_miles == sorted(route_miles)
    for candidate in results:
        assert candidate.route_mile == pytest.approx(
            candidate.route_fraction * ROUTE_DISTANCE_MILES
        )


@pytest.mark.django_db
def test_on_route_station_has_near_zero_distance_from_route(synthetic_stations):
    results = find_stations_near_route(
        _straight_route_geometry(),
        ROUTE_DISTANCE_MILES,
        corridor_radius_miles=CORRIDOR_MILES,
    )
    on_route = next(
        candidate
        for candidate in results
        if candidate.station_id == synthetic_stations["on_route"].pk
    )
    assert on_route.distance_from_route_miles < 0.1


@pytest.mark.django_db
def test_two_mile_offset_distance_is_approximately_two_miles(synthetic_stations):
    results = find_stations_near_route(
        _straight_route_geometry(),
        ROUTE_DISTANCE_MILES,
        corridor_radius_miles=CORRIDOR_MILES,
    )
    two_miles = next(
        candidate
        for candidate in results
        if candidate.station_id == synthetic_stations["two_miles"].pk
    )
    assert two_miles.distance_from_route_miles == pytest.approx(2.0, abs=0.3)


@pytest.mark.django_db
def test_single_query_no_n_plus_one(django_assert_num_queries, synthetic_stations):
    with django_assert_num_queries(1):
        find_stations_near_route(
            _straight_route_geometry(),
            ROUTE_DISTANCE_MILES,
            corridor_radius_miles=CORRIDOR_MILES,
        )
