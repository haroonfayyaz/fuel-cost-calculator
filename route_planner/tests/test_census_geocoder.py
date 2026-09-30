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
