"""Routing provider abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class GeocodedLocation:
    latitude: float
    longitude: float
    formatted_address: str


@dataclass(frozen=True)
class RoutePoint:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class RouteResult:
    geometry: dict
    total_distance_meters: float
    total_distance_miles: float
    duration_seconds: float


class RoutingError(Exception):
    """Base class for routing integration errors."""


class GeocodingError(RoutingError):
    """Geocoding could not be completed."""


class GeocodingNotFoundError(GeocodingError):
    """No geocoding results were returned."""


class GeocodingOutsideUSAError(GeocodingError):
    """Geocoding result is outside the United States."""


class RouteError(RoutingError):
    """Route lookup could not be completed."""


class RoutingBadRequestError(RouteError):
    """The routing provider rejected the request (HTTP 400)."""


class RoutingAuthenticationError(RouteError):
    """Invalid or missing routing API credentials (HTTP 401/403)."""


class RoutingNotFoundError(RouteError):
    """Routing endpoint or resource not found (HTTP 404)."""


class RoutingRateLimitError(RouteError):
    """Routing provider rate limit exceeded (HTTP 429)."""


class RoutingServerError(RouteError):
    """Routing provider server error (HTTP 5xx)."""


class RoutingInvalidResponseError(RouteError):
    """Routing provider returned an invalid or unexpected payload."""


@runtime_checkable
class RoutingProvider(Protocol):
    def geocode_location(self, text: str) -> GeocodedLocation:
        """Forward-geocode free text restricted to U.S. results."""

    def get_route(self, start: RoutePoint, finish: RoutePoint) -> RouteResult:
        """Return driving route geometry and summary metrics."""
