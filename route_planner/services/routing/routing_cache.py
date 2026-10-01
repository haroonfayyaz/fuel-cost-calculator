"""Deterministic cache keys and safe cache access for routing integrations."""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.core.cache import cache

from route_planner.services.routing.base import GeocodedLocation, RoutePoint, RouteResult

logger = logging.getLogger(__name__)

DEFAULT_ROUTING_PROFILE = "driving-car"
DEFAULT_ROUTING_CACHE_VERSION = "1"


def normalize_geocode_query(text: str) -> str:
    """Normalize free-text geocode input (not used as the sole cache key)."""
    return " ".join(text.strip().split()).casefold()


def geocode_cache_key(normalized_query: str) -> str:
    digest = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
    return f"routing:geocode:{digest}"


def round_coordinate_for_cache(value: float, *, decimal_places: int) -> str:
    """
    Round WGS84 coordinates for route cache keys.

    Four decimal places (~11 m latitude) keeps distinct road endpoints separate
    while collapsing GPS noise.
    """
    if decimal_places < 1:
        raise ValueError("decimal_places must be at least 1.")
    quantizer = Decimal("1").scaleb(-decimal_places)
    rounded = Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP)
    return format(rounded, "f")


def route_endpoint_cache_token(point: RoutePoint, *, decimal_places: int) -> str:
    lat = round_coordinate_for_cache(point.latitude, decimal_places=decimal_places)
    lon = round_coordinate_for_cache(point.longitude, decimal_places=decimal_places)
    return f"{lat},{lon}"


def route_cache_key(
    start: RoutePoint,
    finish: RoutePoint,
    *,
    profile: str,
    version: str,
    decimal_places: int,
) -> str:
    start_token = route_endpoint_cache_token(start, decimal_places=decimal_places)
    finish_token = route_endpoint_cache_token(finish, decimal_places=decimal_places)
    material = f"{profile}|{version}|{start_token}|{finish_token}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"routing:route:{digest}"


def serialize_route_result(result: RouteResult) -> dict[str, Any]:
    return {
        "geometry": result.geometry,
        "total_distance_meters": result.total_distance_meters,
        "total_distance_miles": result.total_distance_miles,
        "duration_seconds": result.duration_seconds,
    }


def deserialize_route_result(payload: dict[str, Any]) -> RouteResult:
    return RouteResult(
        geometry=payload["geometry"],
        total_distance_meters=float(payload["total_distance_meters"]),
        total_distance_miles=float(payload["total_distance_miles"]),
        duration_seconds=float(payload["duration_seconds"]),
    )


def serialize_geocoded_location(location: GeocodedLocation) -> dict[str, Any]:
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "formatted_address": location.formatted_address,
    }


def deserialize_geocoded_location(payload: dict[str, Any]) -> GeocodedLocation:
    return GeocodedLocation(
        latitude=float(payload["latitude"]),
        longitude=float(payload["longitude"]),
        formatted_address=str(payload["formatted_address"]),
    )


def safe_cache_get(key: str) -> Any | None:
    try:
        return cache.get(key)
    except Exception:
        logger.warning("Cache get failed for key %s", key, exc_info=True)
        return None


def safe_cache_set(key: str, value: Any, *, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning("Cache set failed for key %s", key, exc_info=True)
