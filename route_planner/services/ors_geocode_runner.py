"""Geocode imported FuelStation rows via the routing provider (Pelias / ORS)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from django.contrib.gis.geos import Point
from django.utils import timezone

from route_planner.models import FuelStation
from route_planner.services.fuel_station_geocode import fuel_station_geocode_queries
from route_planner.services.geocode_persistence import (
    GeocodeWriteBuffer,
    apply_geocode_failed,
    apply_geocode_matched,
    apply_geocode_unmatched,
)
from route_planner.services.geocode_runner import GeocodeRunSummary, stations_to_geocode
from route_planner.services.routing.base import (
    GeocodingError,
    GeocodingNotFoundError,
    RoutingError,
    RoutingProvider,
    RoutingRateLimitError,
)

logger = logging.getLogger(__name__)


class OrsGeocodeBudgetExhausted(Exception):
    """Raised when ``max_api_requests`` would be exceeded."""


@dataclass
class _ApiRequestBudget:
    max_requests: int | None
    used: int = 0

    def consume(self) -> None:
        if self.max_requests is not None and self.used >= self.max_requests:
            raise OrsGeocodeBudgetExhausted()
        self.used += 1


def geocode_station_with_provider(
    station: FuelStation,
    provider: RoutingProvider,
    *,
    budget: _ApiRequestBudget,
    single_query_only: bool = False,
) -> Point | None:
    """Return a WGS84 point or ``None`` when no U.S. match is found."""
    queries = fuel_station_geocode_queries(station)
    if single_query_only and queries:
        queries = queries[:1]

    for query in queries:
        budget.consume()
        try:
            result = provider.geocode_location(query)
        except GeocodingNotFoundError:
            continue
        except GeocodingError:
            continue
        return Point(result.longitude, result.latitude, srid=4326)

    return None


def _save_matched(station: FuelStation, location: Point) -> None:
    """Immediate single-row save (tests and legacy callers)."""
    apply_geocode_matched(station, location)
    station.save(update_fields=["location", "geocoding_status", "geocoded_at", "updated_at"])


def _save_unmatched(station: FuelStation) -> None:
    apply_geocode_unmatched(station)
    station.save(update_fields=["location", "geocoding_status", "geocoded_at", "updated_at"])


def _save_failed(station: FuelStation) -> None:
    apply_geocode_failed(station)
    station.save(update_fields=["geocoding_status", "geocoded_at", "updated_at"])


def run_ors_geocode_job(
    provider: RoutingProvider,
    *,
    force: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    delay_seconds: float = 0.0,
    max_api_requests: int | None = None,
    single_query_only: bool = False,
    db_batch_size: int = 100,
) -> GeocodeRunSummary:
    """
    Geocode stations that still lack a ``location``.

    Does not re-import CSV data; updates existing ``FuelStation`` rows in place.
    Each Pelias call counts toward ``max_api_requests`` (use ~2800/day on a 3000 quota).
    """
    stations, skipped = stations_to_geocode(force=force, limit=limit)
    summary = GeocodeRunSummary(skipped=skipped, eligible=len(stations))
    budget = _ApiRequestBudget(max_requests=max_api_requests)

    if dry_run:
        return summary

    if not stations:
        return summary

    with GeocodeWriteBuffer(batch_size=db_batch_size) as writes:
        for index, station in enumerate(stations):
            now = timezone.now()
            try:
                point = geocode_station_with_provider(
                    station,
                    provider,
                    budget=budget,
                    single_query_only=single_query_only,
                )
                if point is not None:
                    apply_geocode_matched(station, point, now=now)
                    summary.matched += 1
                else:
                    apply_geocode_unmatched(station, now=now)
                    summary.unmatched += 1
                writes.stage(station)
            except OrsGeocodeBudgetExhausted:
                summary.stopped_for_api_budget = True
                break
            except RoutingRateLimitError:
                logger.warning("ORS geocoding rate limit hit at station pk=%s", station.pk)
                apply_geocode_failed(station, now=now)
                writes.stage(station)
                summary.failed += 1
                raise
            except RoutingError:
                logger.warning("ORS geocoding failed for station pk=%s", station.pk, exc_info=True)
                apply_geocode_failed(station, now=now)
                writes.stage(station)
                summary.failed += 1
            except Exception:
                logger.exception("Unexpected geocoding failure for station pk=%s", station.pk)
                apply_geocode_failed(station, now=now)
                writes.stage(station)
                summary.failed += 1

            if delay_seconds > 0 and index + 1 < len(stations):
                time.sleep(delay_seconds)

    summary.api_requests = budget.used
    return summary
