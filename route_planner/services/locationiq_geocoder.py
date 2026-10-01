"""LocationIQ geocoding (OSM-based, higher free-tier limits than public Nominatim)."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any
from urllib.parse import urljoin

import requests
from django.contrib.gis.geos import Point
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_LOCATIONIQ_BASE_URL = "https://us1.locationiq.com/v1/"

RETRYABLE_HTTP_STATUS = frozenset({429, 502, 503})
MAX_HTTP_ATTEMPTS = 4

_throttle_lock = threading.Lock()
_last_request_monotonic = 0.0


class LocationIQGeocoderError(Exception):
    """LocationIQ request or response error."""


class LocationIQRateLimitedError(LocationIQGeocoderError):
    """Rate limit exceeded."""


def locationiq_cache_key(query: str) -> str:
    normalized = " ".join(query.strip().split()).casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"locationiq:search:{digest}"


def _wait_for_request_slot(min_interval_seconds: float) -> None:
    global _last_request_monotonic
    if min_interval_seconds <= 0:
        return
    with _throttle_lock:
        now = time.monotonic()
        elapsed = now - _last_request_monotonic
        if elapsed < min_interval_seconds:
            time.sleep(min_interval_seconds - elapsed)
        _last_request_monotonic = time.monotonic()


def search_us_location(
    query: str,
    *,
    api_key: str,
    base_url: str = DEFAULT_LOCATIONIQ_BASE_URL,
    timeout_seconds: float = 30.0,
    min_request_interval_seconds: float = 0.5,
    session: requests.Session | None = None,
) -> Point | None:
    if not api_key:
        raise LocationIQGeocoderError("LOCATIONIQ_API_KEY is not configured.")

    cache_key = locationiq_cache_key(query)
    cached = cache.get(cache_key)
    if cached == "MISS":
        return None
    if isinstance(cached, dict):
        return Point(cached["lon"], cached["lat"], srid=4326)

    http = session or requests.Session()
    url = urljoin(base_url.rstrip("/") + "/", "search")
    params = {
        "key": api_key,
        "q": query.strip(),
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }

    last_error: Exception | None = None
    for attempt in range(MAX_HTTP_ATTEMPTS):
        _wait_for_request_slot(min_request_interval_seconds)
        try:
            response = http.get(url, params=params, timeout=timeout_seconds)
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < MAX_HTTP_ATTEMPTS:
                time.sleep(min(30.0, 2.0 * (attempt + 1)))
                continue
            raise LocationIQGeocoderError("LocationIQ request failed.") from exc

        if response.status_code in RETRYABLE_HTTP_STATUS:
            sleep_for = min(60.0, 5.0 * (2**attempt))
            logger.warning(
                "LocationIQ HTTP %s; sleeping %.0fs",
                response.status_code,
                sleep_for,
            )
            time.sleep(sleep_for)
            last_error = LocationIQRateLimitedError(f"HTTP {response.status_code}")
            continue

        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.HTTPError, ValueError) as exc:
            raise LocationIQGeocoderError("LocationIQ returned an invalid response.") from exc

        if not isinstance(payload, list) or not payload:
            cache.set(cache_key, "MISS", timeout=86400 * 7)
            return None

        hit: dict[str, Any] = payload[0]
        try:
            lat = float(hit["lat"])
            lon = float(hit["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LocationIQGeocoderError("LocationIQ result missing coordinates.") from exc

        cache.set(cache_key, {"lat": lat, "lon": lon}, timeout=86400 * 30)
        return Point(lon, lat, srid=4326)

    raise LocationIQRateLimitedError("LocationIQ rate limit persisted after retries.") from last_error
