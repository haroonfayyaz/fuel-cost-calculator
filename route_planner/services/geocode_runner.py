from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from route_planner.models import FuelStation
from route_planner.services.census_geocoder import (
    CensusGeocoderError,
    GeocodeBatchResult,
    GeocodeOutcome,
    StationAddress,
    geocode_station_addresses,
)


@dataclass
class GeocodeRunSummary:
    matched: int = 0
    unmatched: int = 0
    failed: int = 0
    skipped: int = 0

    def as_text(self) -> str:
        return (
            f"Matched: {self.matched}\n"
            f"Unmatched: {self.unmatched}\n"
            f"Failed: {self.failed}\n"
            f"Skipped: {self.skipped}\n"
        )


def stations_to_geocode(*, force: bool, limit: int | None):
    queryset = FuelStation.objects.us_only().order_by("pk")
    if force:
        eligible = queryset
    else:
        eligible = queryset.filter(location__isnull=True)

    if limit is not None:
        eligible = eligible[:limit]

    skipped = 0
    if not force:
        skipped = queryset.filter(
            location__isnull=False,
            geocoding_status=FuelStation.GeocodingStatus.MATCHED,
        ).count()

    return list(eligible), skipped


def fuel_station_to_address(station: FuelStation) -> StationAddress:
    return StationAddress(
        unique_id=str(station.pk),
        street=station.address,
        city=station.city,
        state=station.state,
        zip_code="",
    )


def apply_geocode_results(results: dict[str, GeocodeBatchResult]) -> GeocodeRunSummary:
    summary = GeocodeRunSummary()
    now = timezone.now()

    with transaction.atomic():
        for unique_id, result in results.items():
            station = FuelStation.objects.select_for_update().get(pk=int(unique_id))
            if result.outcome == GeocodeOutcome.MATCHED and result.location is not None:
                station.location = result.location
                station.geocoding_status = FuelStation.GeocodingStatus.MATCHED
                station.geocoded_at = now
                station.save(update_fields=["location", "geocoding_status", "geocoded_at", "updated_at"])
                summary.matched += 1
            elif result.outcome == GeocodeOutcome.UNMATCHED:
                station.location = None
                station.geocoding_status = FuelStation.GeocodingStatus.UNMATCHED
                station.geocoded_at = now
                station.save(
                    update_fields=["location", "geocoding_status", "geocoded_at", "updated_at"]
                )
                summary.unmatched += 1
            else:
                station.geocoding_status = FuelStation.GeocodingStatus.FAILED
                station.geocoded_at = now
                station.save(update_fields=["geocoding_status", "geocoded_at", "updated_at"])
                summary.failed += 1

    return summary


def mark_batch_failed(station_ids: list[int]) -> int:
    now = timezone.now()
    updated = FuelStation.objects.filter(pk__in=station_ids).update(
        geocoding_status=FuelStation.GeocodingStatus.FAILED,
        geocoded_at=now,
    )
    return updated


def run_geocode_job(
    *,
    force: bool,
    limit: int | None,
    dry_run: bool,
    batch_url: str,
    benchmark: str,
    batch_size: int,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    session=None,
) -> GeocodeRunSummary:
    stations, skipped = stations_to_geocode(force=force, limit=limit)
    summary = GeocodeRunSummary(skipped=skipped)

    if dry_run or not stations:
        return summary

    addresses = [fuel_station_to_address(station) for station in stations]
    station_ids = [station.pk for station in stations]

    try:
        results = geocode_station_addresses(
            addresses,
            batch_url=batch_url,
            benchmark=benchmark,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            session=session,
        )
    except (CensusGeocoderError, ValueError):
        summary.failed += mark_batch_failed(station_ids)
        return summary

    applied = apply_geocode_results(results)
    summary.matched += applied.matched
    summary.unmatched += applied.unmatched
    summary.failed += applied.failed
    return summary
