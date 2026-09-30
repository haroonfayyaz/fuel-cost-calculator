"""Tests for LocationIQ bulk geocoding."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point

from route_planner.models import FuelStation
from route_planner.services.locationiq_geocode_runner import run_locationiq_geocode_job


@pytest.fixture
def station(db):
    return FuelStation.objects.create(
        opis_truckstop_id="777",
        name="Test Stop",
        address="100 Main",
        city="Dallas",
        state="TX",
        rack_id="1",
        retail_price=Decimal("3.00"),
        source_line_number=777001,
    )


def test_locationiq_geocode_job_matched(station):
    with patch(
        "route_planner.services.locationiq_geocode_runner.search_us_location",
        return_value=Point(-96.8, 32.7, srid=4326),
    ):
        summary = run_locationiq_geocode_job(
            api_key="test-key",
            base_url="https://us1.locationiq.com/v1",
            timeout_seconds=5,
            limit=1,
        )

    station.refresh_from_db()
    assert summary.matched == 1
    assert station.geocoding_status == FuelStation.GeocodingStatus.MATCHED
