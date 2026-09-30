"""Shared loop for bulk station geocoding (any HTTP geocoder backend)."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable

from django.contrib.gis.geos import Point
from django.utils import timezone

from route_planner.models import FuelStation
from route_planner.services.geocode_persistence import (
    GeocodeWriteBuffer,
    apply_geocode_failed,
    apply_geocode_matched,
    apply_geocode_unmatched,
)
from route_planner.services.geocode_runner import GeocodeRunSummary, stations_to_geocode
from route_planner.services.ors_geocode_runner import OrsGeocodeBudgetExhausted, _ApiRequestBudget

logger = logging.getLogger(__name__)


class GeocodeRateLimitStop(Exception):
    """Stop the job after rate limiting (row left unchanged if raised mid-station)."""


def run_bulk_geocode_job(
    resolve_point: Callable[[FuelStation, _ApiRequestBudget], Point | None],
    *,
    force: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    delay_seconds: float = 0.0,
    max_api_requests: int | None = None,
    db_batch_size: int = 100,
    progress_every: int = 25,
    rate_limit_exception: type[BaseException] | tuple[type[BaseException], ...] = (),
) -> GeocodeRunSummary:
    stations, skipped = stations_to_geocode(force=force, limit=limit)
    summary = GeocodeRunSummary(skipped=skipped, eligible=len(stations))
    budget = _ApiRequestBudget(max_requests=max_api_requests)

    if dry_run or not stations:
        return summary

    with GeocodeWriteBuffer(batch_size=db_batch_size) as writes:
        for index, station in enumerate(stations):
            now = timezone.now()
            try:
                point = resolve_point(station, budget)
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
            except rate_limit_exception:
                logger.error("Geocoder rate limit — stopping job; retry later.")
                summary.stopped_for_api_budget = True
                break
            except GeocodeRateLimitStop:
                summary.stopped_for_api_budget = True
                break
            except Exception:
                logger.exception("Unexpected geocoding failure for station pk=%s", station.pk)
                apply_geocode_failed(station, now=now)
                writes.stage(station)
                summary.failed += 1

            if delay_seconds > 0 and index + 1 < len(stations):
                time.sleep(delay_seconds)

            if progress_every > 0 and (index + 1) % progress_every == 0:
                print(
                    f"Progress: {index + 1}/{len(stations)} "
                    f"(matched={summary.matched}, unmatched={summary.unmatched}, failed={summary.failed}, "
                    f"api_calls={budget.used})",
                    file=sys.stderr,
                    flush=True,
                )

    summary.api_requests = budget.used
    return summary
