"""Tests for Nominatim bulk geocoding."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point

from route_planner.models import FuelStation
from route_planner.services.nominatim_geocoder import nominatim_cache_key
from route_planner.services.nominatim_geocode_runner import run_nominatim_geocode_job


@pytest.fixture
def station(db):
    return FuelStation.objects.create(
        opis_truckstop_id="888",
        name="Test Stop",
        address="100 Main",
        city="Dallas",
        state="TX",
        rack_id="1",
        retail_price=Decimal("3.00"),
        source_line_number=888001,
    )


def test_nominatim_cache_key_is_hashed():
    key = nominatim_cache_key("I-55, Exit 4 & I-40, West Memphis, AR")
    assert " " not in key
    assert "&" not in key
    assert key.startswith("nominatim:search:")
    assert len(key.split(":")[-1]) == 64


def test_nominatim_geocode_job_matched(station):
    with patch(
        "route_planner.services.nominatim_geocode_runner.search_us_location",
        return_value=Point(-96.8, 32.7, srid=4326),
    ):
        summary = run_nominatim_geocode_job(
            user_agent="TestApp/1.0 test@example.com",
            timeout_seconds=5,
            limit=1,
            delay_seconds=0,
        )

    station.refresh_from_db()
    assert summary.matched == 1
    assert station.geocoding_status == FuelStation.GeocodingStatus.MATCHED
