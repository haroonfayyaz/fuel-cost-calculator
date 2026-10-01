from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.contrib.gis.geos import Point

from route_planner.models import FuelStation
import csv
import io

from route_planner.services.census_geocoder import (
    CensusGeocoderError,
    GeocodeOutcome,
    StationAddress,
    build_batch_csv_rows,
    chunk_stations,
    parse_batch_response,
    submit_address_batch,
)
from route_planner.services.geocode_runner import run_geocode_job


def _census_row(
    unique_id: str,
    match: str,
    lon: str = "",
    lat: str = "",
) -> str:
    return (
        f'"{unique_id}","123 Main","{match}","Exact","123 Main, City, ST",'
        f'"{lon}","{lat}","12345","L"\n'
    )


def test_build_batch_csv_leaves_zip_blank():
    payload = build_batch_csv_rows(
        [StationAddress("1", "123 Main", "Denver", "CO")]
    )
    rows = list(csv.reader(io.StringIO(payload)))
    assert rows[0] == ["1", "123 Main", "Denver", "CO", ""]


def test_parse_matched_address():
    response = _census_row("42", "Match", "-104.9903", "39.7392")
    results = parse_batch_response(response)
    assert results["42"].outcome == GeocodeOutcome.MATCHED
    assert results["42"].location.x == pytest.approx(-104.9903)
    assert results["42"].location.y == pytest.approx(39.7392)


def test_parse_unmatched_address():
    response = _census_row("7", "No_Match")
    results = parse_batch_response(response)
    assert results["7"].outcome == GeocodeOutcome.UNMATCHED
    assert results["7"].location is None


def test_parse_malformed_response_raises():
    with pytest.raises(CensusGeocoderError):
        parse_batch_response("only-one-column\n")


def test_submit_batch_retries_on_timeout():
    session = MagicMock()
    session.post.side_effect = [
        requests.Timeout("timed out"),
        MagicMock(text=_census_row("1", "Match", "-95.0", "35.0"), raise_for_status=lambda: None),
    ]
    text = submit_address_batch(
        [StationAddress("1", "123 Main", "Tulsa", "OK")],
        batch_url="https://example.test/batch",
        benchmark="Public_AR_Current",
        timeout_seconds=1,
        max_retries=2,
        retry_backoff_seconds=0,
        session=session,
    )
    assert "Match" in text
    assert session.post.call_count == 2


def test_submit_batch_raises_after_exhausted_retries():
    session = MagicMock()
    session.post.side_effect = requests.Timeout("timed out")
    with pytest.raises(CensusGeocoderError):
        submit_address_batch(
            [StationAddress("1", "123 Main", "Tulsa", "OK")],
            batch_url="https://example.test/batch",
            benchmark="Public_AR_Current",
            timeout_seconds=1,
            max_retries=2,
            retry_backoff_seconds=0,
            session=session,
        )


def test_chunk_stations_respects_census_max():
    stations = [
        StationAddress(str(index), "Addr", "City", "TX") for index in range(10005)
    ]
    batches = chunk_stations(stations, batch_size=10000)
    assert len(batches) == 2
    assert len(batches[0]) == 10000
    assert len(batches[1]) == 5


@pytest.mark.django_db
def test_run_geocode_job_matched_updates_station():
    station = FuelStation.objects.create(
        opis_truckstop_id="1",
        name="Test",
        address="123 Main",
        city="Denver",
        state="CO",
        rack_id="1",
        retail_price=Decimal("3.500000"),
        source_line_number=10,
    )
    response = _census_row(str(station.pk), "Match", "-104.9903", "39.7392")

    with patch(
        "route_planner.services.geocode_runner.geocode_station_addresses",
        return_value={
            str(station.pk): parse_batch_response(response)[str(station.pk)],
        },
    ):
        summary = run_geocode_job(
            force=False,
            limit=None,
            dry_run=False,
            batch_url="https://example.test/batch",
            benchmark="Public_AR_Current",
            batch_size=1000,
            timeout_seconds=1,
            max_retries=1,
            retry_backoff_seconds=0,
        )

    station.refresh_from_db()
    assert summary.matched == 1
    assert station.location.x == pytest.approx(-104.9903)
    assert station.location.y == pytest.approx(39.7392)
    assert station.geocoding_status == FuelStation.GeocodingStatus.MATCHED


@pytest.mark.django_db
def test_already_geocoded_station_is_skipped():
    station = FuelStation.objects.create(
        opis_truckstop_id="2",
        name="Done",
        address="456 Oak",
        city="Austin",
        state="TX",
        rack_id="1",
        retail_price=Decimal("3.100000"),
        source_line_number=11,
        location=Point(-97.7431, 30.2672, srid=4326),
        geocoding_status=FuelStation.GeocodingStatus.MATCHED,
    )

    with patch("route_planner.services.geocode_runner.geocode_station_addresses") as mock_geocode:
        summary = run_geocode_job(
            force=False,
            limit=None,
            dry_run=False,
            batch_url="https://example.test/batch",
            benchmark="Public_AR_Current",
            batch_size=1000,
            timeout_seconds=1,
            max_retries=1,
            retry_backoff_seconds=0,
        )

    mock_geocode.assert_not_called()
    assert summary.skipped == 1
    station.refresh_from_db()
    assert station.geocoding_status == FuelStation.GeocodingStatus.MATCHED


@pytest.mark.django_db
def test_malformed_census_response_marks_failed():
    station = FuelStation.objects.create(
        opis_truckstop_id="3",
        name="Fail",
        address="789 Pine",
        city="Omaha",
        state="NE",
        rack_id="1",
        retail_price=Decimal("3.200000"),
        source_line_number=12,
    )

    with patch(
        "route_planner.services.geocode_runner.geocode_station_addresses",
        side_effect=CensusGeocoderError("bad response"),
    ):
        summary = run_geocode_job(
            force=False,
            limit=None,
            dry_run=False,
            batch_url="https://example.test/batch",
            benchmark="Public_AR_Current",
            batch_size=1000,
            timeout_seconds=1,
            max_retries=1,
            retry_backoff_seconds=0,
        )

    station.refresh_from_db()
    assert summary.failed == 1
    assert station.geocoding_status == FuelStation.GeocodingStatus.FAILED


@pytest.mark.django_db
def test_longitude_latitude_order():
    station = FuelStation.objects.create(
        opis_truckstop_id="4",
        name="Order",
        address="1 Main",
        city="Tulsa",
        state="OK",
        rack_id="1",
        retail_price=Decimal("3.000000"),
        source_line_number=13,
    )
    lon, lat = -95.9928, 36.1540
    response = _census_row(str(station.pk), "Match", str(lon), str(lat))

    with patch(
        "route_planner.services.geocode_runner.geocode_station_addresses",
        return_value={str(station.pk): parse_batch_response(response)[str(station.pk)]},
    ):
        run_geocode_job(
            force=False,
            limit=None,
            dry_run=False,
            batch_url="https://example.test/batch",
            benchmark="Public_AR_Current",
            batch_size=1000,
            timeout_seconds=1,
            max_retries=1,
            retry_backoff_seconds=0,
        )

    station.refresh_from_db()
    assert station.location.x == pytest.approx(lon)
    assert station.location.y == pytest.approx(lat)


# --- ORS/Pelias station geocoding (mocked provider) ---


from unittest.mock import create_autospec

from route_planner.services.fuel_station_geocode import fuel_station_geocode_queries
from route_planner.services.ors_geocode_runner import (
    _ApiRequestBudget,
    geocode_station_with_provider,
    run_ors_geocode_job,
)
from route_planner.services.routing.base import GeocodedLocation, GeocodingNotFoundError, RoutingProvider


@pytest.fixture
def ors_station(db):
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


def test_fuel_station_geocode_queries_include_address_and_name(ors_station):
    queries = fuel_station_geocode_queries(ors_station)
    assert any("I-40" in query for query in queries)
    assert any("Pilot" in query for query in queries)


def test_geocode_station_with_provider_uses_fallback_query(ors_station):
    provider = create_autospec(RoutingProvider, instance=True)
    provider.geocode_location.side_effect = [
        GeocodingNotFoundError("no match"),
        GeocodedLocation(latitude=35.5, longitude=-97.5, formatted_address="Matched"),
    ]
    point = geocode_station_with_provider(ors_station, provider, budget=_ApiRequestBudget(max_requests=None))
    assert point is not None
    assert provider.geocode_location.call_count == 2


@pytest.mark.django_db
def test_run_ors_geocode_job_marks_unmatched_when_no_results(ors_station):
    provider = create_autospec(RoutingProvider, instance=True)
    provider.geocode_location.side_effect = GeocodingNotFoundError("missing")
    summary = run_ors_geocode_job(provider, limit=1)
    ors_station.refresh_from_db()
    assert summary.unmatched == 1
    assert ors_station.geocoding_status == FuelStation.GeocodingStatus.UNMATCHED


# --- Nominatim bulk geocoding (mocked HTTP) ---


from route_planner.services.nominatim_geocoder import nominatim_cache_key
from route_planner.services.nominatim_geocode_runner import run_nominatim_geocode_job


@pytest.fixture
def nominatim_station(db):
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
    assert key.startswith("nominatim:search:")
    assert len(key.split(":")[-1]) == 64


@pytest.mark.django_db
def test_nominatim_geocode_job_matched(nominatim_station):
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
    nominatim_station.refresh_from_db()
    assert summary.matched == 1


@pytest.mark.django_db
def test_nominatim_geocode_job_marks_unmatched_when_search_returns_none(nominatim_station):
    with patch(
        "route_planner.services.nominatim_geocode_runner.search_us_location",
        return_value=None,
    ):
        summary = run_nominatim_geocode_job(
            user_agent="TestApp/1.0 test@example.com",
            timeout_seconds=5,
            limit=1,
            delay_seconds=0,
        )
    nominatim_station.refresh_from_db()
    assert summary.unmatched == 1


@pytest.mark.django_db
def test_nominatim_geocode_job_handles_timeout(nominatim_station):
    with patch(
        "route_planner.services.nominatim_geocode_runner.search_us_location",
        side_effect=requests.Timeout("slow"),
    ):
        summary = run_nominatim_geocode_job(
            user_agent="TestApp/1.0 test@example.com",
            timeout_seconds=5,
            limit=1,
            delay_seconds=0,
        )
    nominatim_station.refresh_from_db()
    assert summary.failed >= 1


# --- LocationIQ bulk geocoding (mocked HTTP) ---


from route_planner.services.locationiq_geocode_runner import run_locationiq_geocode_job


@pytest.fixture
def locationiq_station(db):
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


@pytest.mark.django_db
def test_locationiq_geocode_job_matched(locationiq_station):
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
    locationiq_station.refresh_from_db()
    assert summary.matched == 1


@pytest.mark.django_db
def test_locationiq_geocode_job_marks_unmatched_when_search_returns_none(locationiq_station):
    with patch(
        "route_planner.services.locationiq_geocode_runner.search_us_location",
        return_value=None,
    ):
        summary = run_locationiq_geocode_job(
            api_key="test-key",
            base_url="https://us1.locationiq.com/v1",
            timeout_seconds=5,
            limit=1,
        )
    locationiq_station.refresh_from_db()
    assert summary.unmatched == 1


@pytest.mark.django_db
def test_run_geocode_job_unmatched_updates_station(db):
    station = FuelStation.objects.create(
        opis_truckstop_id="5",
        name="Unmatched",
        address="1 Main",
        city="Nowhere",
        state="OK",
        rack_id="1",
        retail_price=Decimal("3.000000"),
        source_line_number=14,
    )
    response = _census_row(str(station.pk), "No_Match")
    with patch(
        "route_planner.services.geocode_runner.geocode_station_addresses",
        return_value={str(station.pk): parse_batch_response(response)[str(station.pk)]},
    ):
        run_geocode_job(
            force=False,
            limit=None,
            dry_run=False,
            batch_url="https://example.test/batch",
            benchmark="Public_AR_Current",
            batch_size=1000,
            timeout_seconds=1,
            max_retries=1,
            retry_backoff_seconds=0,
        )
    station.refresh_from_db()
    assert station.geocoding_status == FuelStation.GeocodingStatus.UNMATCHED
    assert station.location is None
