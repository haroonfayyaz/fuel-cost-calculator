"""OpenRouteService / HeiGIT routing provider implementation."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin

import requests

from route_planner.services.routing.base import (
    GeocodedLocation,
    GeocodingNotFoundError,
    GeocodingOutsideUSAError,
    RoutePoint,
    RouteResult,
    RoutingAuthenticationError,
    RoutingBadRequestError,
    RoutingInvalidResponseError,
    RoutingNotFoundError,
    RoutingRateLimitError,
    RoutingServerError,
)
from route_planner.services.routing.routing_cache import (
    DEFAULT_ROUTING_CACHE_VERSION,
    DEFAULT_ROUTING_PROFILE,
    deserialize_geocoded_location,
    deserialize_route_result,
    geocode_cache_key,
    normalize_geocode_query,
    route_cache_key,
    safe_cache_get,
    safe_cache_set,
    serialize_geocoded_location,
    serialize_route_result,
)

logger = logging.getLogger(__name__)

METERS_TO_MILES = 0.000621371
USA_COUNTRY_CODES = frozenset({"US", "USA"})
ACCEPT_JSON = "application/json"
ACCEPT_GEOJSON = "application/geo+json"


class OpenRouteServiceProvider:
    """RoutingProvider backed by HeiGIT ORS APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        geocode_cache_timeout_seconds: int,
        route_cache_timeout_seconds: int,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        routing_profile: str = DEFAULT_ROUTING_PROFILE,
        routing_cache_version: str = DEFAULT_ROUTING_CACHE_VERSION,
        route_coordinate_cache_decimals: int = 4,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise RoutingAuthenticationError("ORS_API_KEY is not configured.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.geocode_cache_timeout_seconds = geocode_cache_timeout_seconds
        self.route_cache_timeout_seconds = route_cache_timeout_seconds
        self.routing_profile = routing_profile
        self.routing_cache_version = routing_cache_version
        self.route_coordinate_cache_decimals = route_coordinate_cache_decimals
        self.connect_timeout = connect_timeout_seconds
        self.read_timeout = read_timeout_seconds
        self._session = session or requests.Session()

    def geocode_location(self, text: str) -> GeocodedLocation:
        normalized = normalize_geocode_query(text)
        cache_key = geocode_cache_key(normalized)
        cached = safe_cache_get(cache_key)
        if cached is not None:
            return deserialize_geocoded_location(cached)

        params = {
            "text": text.strip(),
            "boundary.country": "USA",
        }
        url = urljoin(f"{self.base_url}/", "pelias/v1/search")
        payload = self._request_json(
            method="GET",
            url=url,
            params=params,
            accept=ACCEPT_JSON,
        )
        location = self._parse_geocode_payload(payload)
        safe_cache_set(
            cache_key,
            serialize_geocoded_location(location),
            timeout=self.geocode_cache_timeout_seconds,
        )
        return location

    def get_route(self, start: RoutePoint, finish: RoutePoint) -> RouteResult:
        cache_key = route_cache_key(
            start,
            finish,
            profile=self.routing_profile,
            version=self.routing_cache_version,
            decimal_places=self.route_coordinate_cache_decimals,
        )
        cached = safe_cache_get(cache_key)
        if cached is not None:
            return deserialize_route_result(cached)

        url = urljoin(
            f"{self.base_url}/",
            f"openrouteservice/v2/directions/{self.routing_profile}/geojson",
        )
        body = {
            "coordinates": [
                [start.longitude, start.latitude],
                [finish.longitude, finish.latitude],
            ]
        }
        payload = self._request_json(
            method="POST",
            url=url,
            json_body=body,
            accept=ACCEPT_GEOJSON,
        )
        result = self._parse_route_payload(payload)
        safe_cache_set(
            cache_key,
            serialize_route_result(result),
            timeout=self.route_cache_timeout_seconds,
        )
        return result

    def _headers(self, *, accept: str) -> dict[str, str]:
        return {
            "Authorization": self.api_key,
            "Accept": accept,
            "Content-Type": "application/json",
        }

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        accept: str = ACCEPT_JSON,
    ) -> Any:
        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=self._headers(accept=accept),
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.RequestException as exc:
            logger.warning("Routing provider request failed: %s", exc.__class__.__name__)
            raise RoutingServerError("Routing provider request failed.") from exc

        if response.status_code == 400:
            raise RoutingBadRequestError("Routing provider rejected the request.")
        if response.status_code == 406:
            raise RoutingBadRequestError(
                "Routing provider could not satisfy the requested response format."
            )
        if response.status_code in {401, 403}:
            raise RoutingAuthenticationError("Routing provider authentication failed.")
        if response.status_code == 404:
            raise RoutingNotFoundError("Routing provider resource was not found.")
        if response.status_code == 429:
            raise RoutingRateLimitError("Routing provider rate limit exceeded.")
        if response.status_code >= 500:
            raise RoutingServerError("Routing provider returned a server error.")

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RoutingServerError("Routing provider returned an unexpected error.") from exc

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise RoutingInvalidResponseError("Routing provider returned invalid JSON.") from exc

    def _parse_geocode_payload(self, payload: Any) -> GeocodedLocation:
        if not isinstance(payload, dict):
            raise RoutingInvalidResponseError("Geocoding response must be a JSON object.")

        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise GeocodingNotFoundError("No geocoding results found.")

        feature = features[0]
        if not isinstance(feature, dict):
            raise RoutingInvalidResponseError("Geocoding feature must be an object.")

        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise RoutingInvalidResponseError("Geocoding feature is missing properties or geometry.")

        if not self._is_us_result(properties):
            raise GeocodingOutsideUSAError("Geocoding result is outside the United States.")

        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise RoutingInvalidResponseError("Geocoding geometry coordinates are missing.")

        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
        formatted_address = str(properties.get("label") or properties.get("name") or "").strip()
        if not formatted_address:
            raise RoutingInvalidResponseError("Geocoding result is missing a formatted address.")

        return GeocodedLocation(
            latitude=latitude,
            longitude=longitude,
            formatted_address=formatted_address,
        )

    @staticmethod
    def _is_us_result(properties: dict[str, Any]) -> bool:
        country = str(properties.get("country_code") or properties.get("country_a") or "").upper()
        if country in USA_COUNTRY_CODES:
            return True
        return str(properties.get("country") or "").strip().lower() in {"united states", "usa"}

    def _parse_route_payload(self, payload: Any) -> RouteResult:
        if not isinstance(payload, dict):
            raise RoutingInvalidResponseError("Route response must be a JSON object.")

        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise RoutingInvalidResponseError("Route response is missing features.")

        feature = features[0]
        if not isinstance(feature, dict):
            raise RoutingInvalidResponseError("Route feature must be an object.")

        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            raise RoutingInvalidResponseError("Route feature is missing geometry or properties.")

        summary = properties.get("summary")
        if not isinstance(summary, dict):
            raise RoutingInvalidResponseError("Route summary is missing.")

        distance_meters = float(summary.get("distance"))
        duration_seconds = float(summary.get("duration"))

        return RouteResult(
            geometry=geometry,
            total_distance_meters=distance_meters,
            total_distance_miles=distance_meters * METERS_TO_MILES,
            duration_seconds=duration_seconds,
        )
