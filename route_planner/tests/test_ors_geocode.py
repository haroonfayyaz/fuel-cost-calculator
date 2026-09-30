"""Tests for ORS/Pelias station geocoding (no CSV re-import)."""

from decimal import Decimal
from unittest.mock import create_autospec

import pytest
from django.contrib.gis.geos import Point

from route_planner.models import FuelStation
from route_planner.services.fuel_station_geocode import fuel_station_geocode_queries
from route_planner.services.ors_geocode_runner import (
    _ApiRequestBudget,
    geocode_station_with_provider,
    run_ors_geocode_job,
)
from route_planner.services.routing.base import (
    GeocodedLocation,
    GeocodingNotFoundError,
    RoutingProvider,
)


@pytest.fixture
def station(db):
    return FuelStation.objects.create(
        opis_truckstop_id="999",
        name="Pilot Travel Center",
        address="I-40, EXIT 140",
        city="Oklahoma City",
        state="OK",
        rack_id="1",
        retail_price=Decimal("3.25"),
        source_line_number=999001,
    )


def test_fuel_station_geocode_queries_include_address_and_name(station):
    queries = fuel_station_geocode_queries(station)
    assert any("I-40" in query for query in queries)
    assert any("Pilot" in query for query in queries)
    assert all("OK" in query for query in queries)


def test_geocode_station_with_provider_uses_fallback_query(station):
    provider = create_autospec(RoutingProvider, instance=True)
    provider.geocode_location.side_effect = [
        GeocodingNotFoundError("no match"),
        GeocodedLocation(
            latitude=35.5,
            longitude=-97.5,
            formatted_address="Pilot, Oklahoma City, OK",
        ),
    ]

    point = geocode_station_with_provider(station, provider, budget=_ApiRequestBudget(max_requests=None))

    assert point is not None
    assert point.y == pytest.approx(35.5)
    assert provider.geocode_location.call_count == 2


def test_run_ors_geocode_job_updates_station(station):
    provider = create_autospec(RoutingProvider, instance=True)
    provider.geocode_location.return_value = GeocodedLocation(
        latitude=35.5,
        longitude=-97.5,
        formatted_address="Matched",
    )

    summary = run_ors_geocode_job(provider, limit=1)

    station.refresh_from_db()
    assert summary.matched == 1
    assert station.geocoding_status == FuelStation.GeocodingStatus.MATCHED
    assert station.location is not None


def test_run_ors_geocode_job_marks_unmatched_when_no_results(station):
    provider = create_autospec(RoutingProvider, instance=True)
    provider.geocode_location.side_effect = GeocodingNotFoundError("missing")

    summary = run_ors_geocode_job(provider, limit=1)

    station.refresh_from_db()
    assert summary.unmatched == 1
    assert station.geocoding_status == FuelStation.GeocodingStatus.UNMATCHED
    assert station.location is None


def test_run_ors_geocode_dry_run_does_not_call_provider(station):
    provider = create_autospec(RoutingProvider, instance=True)

    summary = run_ors_geocode_job(provider, limit=1, dry_run=True)

    assert summary.eligible == 1
    provider.geocode_location.assert_not_called()
    station.refresh_from_db()
    assert station.geocoding_status == FuelStation.GeocodingStatus.PENDING


def test_run_ors_geocode_stops_at_api_budget(station, db):
    second = FuelStation.objects.create(
        opis_truckstop_id="998",
        name="Other Stop",
        address="1 Hwy",
        city="Tulsa",
        state="OK",
        rack_id="1",
        retail_price=Decimal("3.00"),
        source_line_number=999002,
    )
    provider = create_autospec(RoutingProvider, instance=True)
    provider.geocode_location.return_value = GeocodedLocation(
        latitude=35.5,
        longitude=-97.5,
        formatted_address="Matched",
    )

    summary = run_ors_geocode_job(provider, limit=2, max_api_requests=1)

    station.refresh_from_db()
    second.refresh_from_db()
    assert summary.api_requests == 1
    assert summary.stopped_for_api_budget is True
    assert summary.matched == 1
    assert station.geocoding_status == FuelStation.GeocodingStatus.MATCHED
    assert second.geocoding_status == FuelStation.GeocodingStatus.PENDING
