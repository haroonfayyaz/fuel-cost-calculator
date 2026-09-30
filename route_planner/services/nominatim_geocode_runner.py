"""Bulk geocode FuelStation rows via Nominatim (separate from ORS quota)."""

from __future__ import annotations

import logging
import sys
import time

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
from route_planner.services.nominatim_geocoder import NominatimGeocoderError, NominatimRateLimitedError, search_us_location
from route_planner.services.ors_geocode_runner import OrsGeocodeBudgetExhausted, _ApiRequestBudget

logger = logging.getLogger(__name__)


def geocode_station_with_nominatim(
    station: FuelStation,
    *,
    user_agent: str,
    timeout_seconds: float,
    budget: _ApiRequestBudget,
    single_query_only: bool = False,
    session=None,
    min_request_interval_seconds: float = 1.0,
) -> Point | None:
    queries = fuel_station_geocode_queries(station)
    if single_query_only and queries:
        queries = queries[:1]

    for query in queries:
        budget.consume()
        try:
            point = search_us_location(
                query,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                min_request_interval_seconds=min_request_interval_seconds,
                session=session,
            )
        except NominatimRateLimitedError:
            raise
        except NominatimGeocoderError:
            continue
        if point is not None:
            return point

    return None


def run_nominatim_geocode_job(
    *,
    user_agent: str,
    timeout_seconds: float,
    force: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    delay_seconds: float = 1.1,
    max_api_requests: int | None = None,
    single_query_only: bool = False,
    session=None,
    progress_every: int = 25,
    db_batch_size: int = 100,
    min_request_interval_seconds: float = 1.0,
) -> GeocodeRunSummary:
    """
    Geocode stations without using ORS/HeiGIT.

    Public Nominatim allows ~1 request/second — use ``delay_seconds`` accordingly.
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
                point = geocode_station_with_nominatim(
                    station,
                    user_agent=user_agent,
                    timeout_seconds=timeout_seconds,
                    budget=budget,
                    single_query_only=single_query_only,
                    session=session,
                    min_request_interval_seconds=min_request_interval_seconds,
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
            except NominatimRateLimitedError:
                logger.error("Nominatim rate limit — stop and retry later with delay >= 1.0s")
                summary.stopped_for_api_budget = True
                break
            except Exception:
                logger.exception("Unexpected Nominatim failure for station pk=%s", station.pk)
                apply_geocode_failed(station, now=now)
                writes.stage(station)
                summary.failed += 1

            if delay_seconds > 0 and index + 1 < len(stations):
                time.sleep(delay_seconds)

            if progress_every > 0 and (index + 1) % progress_every == 0:
                print(
                    f"Progress: {index + 1}/{len(stations)} stations in this run "
                    f"(matched={summary.matched}, unmatched={summary.unmatched}, failed={summary.failed}, "
                    f"api_calls={budget.used})",
                    file=sys.stderr,
                    flush=True,
                )

    summary.api_requests = budget.used
    return summary
