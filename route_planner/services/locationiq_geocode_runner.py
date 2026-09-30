"""Bulk geocode via LocationIQ (faster quota than public Nominatim)."""

from __future__ import annotations

from django.contrib.gis.geos import Point

from route_planner.models import FuelStation
from route_planner.services.bulk_geocode_runner import run_bulk_geocode_job
from route_planner.services.fuel_station_geocode import fuel_station_geocode_queries
from route_planner.services.geocode_runner import GeocodeRunSummary
from route_planner.services.locationiq_geocoder import (
    LocationIQGeocoderError,
    LocationIQRateLimitedError,
    search_us_location,
)
from route_planner.services.ors_geocode_runner import _ApiRequestBudget


def _resolve_with_locationiq(
    station: FuelStation,
    budget: _ApiRequestBudget,
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
    min_request_interval_seconds: float,
    single_query_only: bool,
    session,
) -> Point | None:
    queries = fuel_station_geocode_queries(station)
    if single_query_only and queries:
        queries = queries[:1]

    for query in queries:
        budget.consume()
        try:
            point = search_us_location(
                query,
                api_key=api_key,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                min_request_interval_seconds=min_request_interval_seconds,
                session=session,
            )
        except LocationIQRateLimitedError:
            raise
        except LocationIQGeocoderError:
            continue
        if point is not None:
            return point
    return None


def run_locationiq_geocode_job(
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
    min_request_interval_seconds: float = 0.5,
    force: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    delay_seconds: float = 0.0,
    max_api_requests: int | None = None,
    single_query_only: bool = False,
    session=None,
    db_batch_size: int = 100,
) -> GeocodeRunSummary:
    def resolve(station: FuelStation, budget: _ApiRequestBudget) -> Point | None:
        return _resolve_with_locationiq(
            station,
            budget,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            min_request_interval_seconds=min_request_interval_seconds,
            single_query_only=single_query_only,
            session=session,
        )

    return run_bulk_geocode_job(
        resolve,
        force=force,
        limit=limit,
        dry_run=dry_run,
        delay_seconds=delay_seconds,
        max_api_requests=max_api_requests,
        db_batch_size=db_batch_size,
        rate_limit_exception=LocationIQRateLimitedError,
    )
