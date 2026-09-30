"""OpenStreetMap Nominatim geocoding (does not use ORS daily quota)."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

import requests
from django.contrib.gis.geos import Point
from django.core.cache import cache

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

RETRYABLE_HTTP_STATUS = frozenset({429, 502, 503})
MAX_HTTP_ATTEMPTS = 4

_throttle_lock = threading.Lock()
_last_request_monotonic = 0.0


class NominatimGeocoderError(Exception):
    """Nominatim request or response error."""


class NominatimRateLimitedError(NominatimGeocoderError):
    """Nominatim rejected requests due to rate limiting."""


def nominatim_cache_key(query: str) -> str:
    normalized = " ".join(query.strip().split()).casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"nominatim:search:{digest}"


def _wait_for_request_slot(min_interval_seconds: float) -> None:
    """Enforce Nominatim's ~1 request/second policy between HTTP calls."""
    global _last_request_monotonic
    if min_interval_seconds <= 0:
        return
    with _throttle_lock:
        now = time.monotonic()
        elapsed = now - _last_request_monotonic
        if elapsed < min_interval_seconds:
            time.sleep(min_interval_seconds - elapsed)
        _last_request_monotonic = time.monotonic()


def _backoff_seconds(attempt: int, response: requests.Response | None) -> float:
    if response is not None and response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 120.0)
    return min(60.0, 5.0 * (2**attempt))


def search_us_location(
    query: str,
    *,
    user_agent: str,
    timeout_seconds: float,
    min_request_interval_seconds: float = 1.0,
    session: requests.Session | None = None,
) -> Point | None:
    """
    Forward-geocode free text restricted to U.S. results.

    Uses Django cache to avoid repeat lookups across long bulk runs.
    """
    cache_key = nominatim_cache_key(query)
    cached = cache.get(cache_key)
    if cached == "MISS":
        return None
    if isinstance(cached, dict):
        return Point(cached["lon"], cached["lat"], srid=4326)

    http = session or requests.Session()
    params = {
        "q": query.strip(),
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    headers = {"User-Agent": user_agent}

    last_error: Exception | None = None
    response: requests.Response | None = None

    for attempt in range(MAX_HTTP_ATTEMPTS):
        _wait_for_request_slot(min_request_interval_seconds)
        try:
            response = http.get(
                NOMINATIM_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=timeout_seconds,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < MAX_HTTP_ATTEMPTS:
                sleep_for = _backoff_seconds(attempt, None)
                logger.info(
                    "Nominatim network error (attempt %s/%s); sleeping %.0fs",
                    attempt + 1,
                    MAX_HTTP_ATTEMPTS,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue
            logger.warning("Nominatim request failed after retries: %s", exc.__class__.__name__)
            raise NominatimGeocoderError("Nominatim geocoding request failed.") from exc

        if response.status_code in RETRYABLE_HTTP_STATUS:
            sleep_for = _backoff_seconds(attempt, response)
            logger.warning(
                "Nominatim HTTP %s (attempt %s/%s); sleeping %.0fs — slow down requests",
                response.status_code,
                attempt + 1,
                MAX_HTTP_ATTEMPTS,
                sleep_for,
            )
            time.sleep(sleep_for)
            last_error = NominatimRateLimitedError(f"HTTP {response.status_code}")
            continue

        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.HTTPError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "Nominatim bad response (HTTP %s)",
                getattr(response, "status_code", "?"),
            )
            raise NominatimGeocoderError("Nominatim geocoding request failed.") from exc

        if not isinstance(payload, list) or not payload:
            cache.set(cache_key, "MISS", timeout=86400 * 7)
            return None

        hit: dict[str, Any] = payload[0]
        try:
            lat = float(hit["lat"])
            lon = float(hit["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NominatimGeocoderError("Nominatim returned an invalid result.") from exc

        cache.set(cache_key, {"lat": lat, "lon": lon}, timeout=86400 * 30)
        return Point(lon, lat, srid=4326)

    raise NominatimRateLimitedError(
        "Nominatim rate limit persisted after retries; increase delays and try again later."
    ) from last_error
