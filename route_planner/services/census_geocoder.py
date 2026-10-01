"""U.S. Census batch geocoder client (offline preprocessing only)."""

from __future__ import annotations

import csv
import io
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable, Sequence

import requests
from django.contrib.gis.geos import Point

logger = logging.getLogger(__name__)

# Census batch limit: 10,000 records and 5MB per submission.
CENSUS_BATCH_MAX_RECORDS = 10_000


class GeocodeOutcome(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    FAILED = "failed"


@dataclass(frozen=True)
class StationAddress:
    unique_id: str
    street: str
    city: str
    state: str
    zip_code: str = ""


@dataclass(frozen=True)
class GeocodeBatchResult:
    unique_id: str
    outcome: GeocodeOutcome
    location: Point | None = None


class CensusGeocoderError(Exception):
    """Raised when the Census batch response cannot be processed."""


def build_batch_csv_rows(stations: Sequence[StationAddress]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for station in stations:
        writer.writerow(
            [
                station.unique_id,
                station.street,
                station.city,
                station.state,
                station.zip_code,
            ]
        )
    return buffer.getvalue()


def chunk_stations(
    stations: Sequence[StationAddress],
    batch_size: int,
) -> list[list[StationAddress]]:
    size = min(batch_size, CENSUS_BATCH_MAX_RECORDS)
    if size <= 0:
        raise ValueError("batch_size must be positive.")
    return [list(stations[index : index + size]) for index in range(0, len(stations), size)]


def parse_batch_response(response_text: str) -> dict[str, GeocodeBatchResult]:
    if not response_text.strip():
        raise CensusGeocoderError("Census batch response was empty.")

    reader = csv.reader(io.StringIO(response_text))
    results: dict[str, GeocodeBatchResult] = {}

    for row in reader:
        if not row:
            continue
        if len(row) < 3:
            raise CensusGeocoderError(f"Unexpected Census row with fewer than 3 columns: {row!r}")

        unique_id = row[0].strip()
        match_indicator = row[2].strip().lower()

        if match_indicator == "match" and len(row) >= 7:
            longitude, latitude = _parse_coordinates(row[5], row[6])
            if longitude is None or latitude is None:
                results[unique_id] = GeocodeBatchResult(unique_id, GeocodeOutcome.UNMATCHED)
                continue
            point = Point(float(longitude), float(latitude), srid=4326)
            results[unique_id] = GeocodeBatchResult(
                unique_id,
                GeocodeOutcome.MATCHED,
                location=point,
            )
            continue

        results[unique_id] = GeocodeBatchResult(unique_id, GeocodeOutcome.UNMATCHED)

    if not results:
        raise CensusGeocoderError("Census batch response contained no parseable rows.")

    return results


def _parse_coordinates(lon_raw: str, lat_raw: str) -> tuple[Decimal | None, Decimal | None]:
    try:
        longitude = Decimal(lon_raw.strip())
        latitude = Decimal(lat_raw.strip())
    except InvalidOperation:
        return None, None
    if longitude == 0 and latitude == 0:
        return None, None
    return longitude, latitude


def submit_address_batch(
    stations: Sequence[StationAddress],
    *,
    batch_url: str,
    benchmark: str,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    session: requests.Session | None = None,
) -> str:
    if not stations:
        raise ValueError("Cannot submit an empty Census batch.")
    if len(stations) > CENSUS_BATCH_MAX_RECORDS:
        raise ValueError(
            f"Census batch exceeds maximum of {CENSUS_BATCH_MAX_RECORDS} records "
            f"({len(stations)} submitted)."
        )

    csv_payload = build_batch_csv_rows(stations)
    http = session or requests.Session()
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = http.post(
                batch_url,
                data={"benchmark": benchmark},
                files={
                    "addressFile": ("addresses.csv", csv_payload.encode("utf-8"), "text/csv"),
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response.text
        except (requests.RequestException, CensusGeocoderError) as exc:
            last_error = exc
            logger.warning(
                "Census batch request failed (attempt %s/%s): %s",
                attempt,
                max_retries,
                exc,
            )
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds * attempt)

    raise CensusGeocoderError("Census batch request failed after retries.") from last_error


def geocode_station_addresses(
    stations: Iterable[StationAddress],
    *,
    batch_url: str,
    benchmark: str,
    batch_size: int,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    session: requests.Session | None = None,
) -> dict[str, GeocodeBatchResult]:
    station_list = list(stations)
    combined: dict[str, GeocodeBatchResult] = {}

    for batch in chunk_stations(station_list, batch_size):
        response_text = submit_address_batch(
            batch,
            batch_url=batch_url,
            benchmark=benchmark,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            session=session,
        )
        parsed = parse_batch_response(response_text)
        for station in batch:
            unique_id = station.unique_id
            if unique_id in parsed:
                combined[unique_id] = parsed[unique_id]
            else:
                combined[unique_id] = GeocodeBatchResult(unique_id, GeocodeOutcome.UNMATCHED)
    return combined
