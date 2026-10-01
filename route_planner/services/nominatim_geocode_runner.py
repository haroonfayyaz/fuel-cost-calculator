"""Bulk geocode FuelStation rows via Nominatim (separate from ORS quota)."""

from __future__ import annotations

from django.contrib.gis.geos import Point

from route_planner.models import FuelStation
from route_planner.services.bulk_geocode_runner import run_bulk_geocode_job
from route_planner.services.fuel_station_geocode import fuel_station_geocode_queries
from route_planner.services.geocode_runner import GeocodeRunSummary
from route_planner.services.nominatim_geocoder import (
    NominatimGeocoderError,
    NominatimRateLimitedError,
    search_us_location,
)
from route_planner.services.ors_geocode_runner import _ApiRequestBudget


def geocode_station_with_nominatim(
    station: FuelStation,
    budget: _ApiRequestBudget,
    *,
    user_agent: str,
    timeout_seconds: float,
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
    db_batch_size: int = 100,
    min_request_interval_seconds: float = 1.0,
) -> GeocodeRunSummary:
    def resolve(station: FuelStation, budget: _ApiRequestBudget) -> Point | None:
        return geocode_station_with_nominatim(
            station,
            budget,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            single_query_only=single_query_only,
            session=session,
            min_request_interval_seconds=min_request_interval_seconds,
        )

    return run_bulk_geocode_job(
        resolve,
        force=force,
        limit=limit,
        dry_run=dry_run,
        delay_seconds=delay_seconds,
        max_api_requests=max_api_requests,
        db_batch_size=db_batch_size,
        rate_limit_exception=NominatimRateLimitedError,
    )
