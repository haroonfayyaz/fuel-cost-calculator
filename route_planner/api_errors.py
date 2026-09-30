"""Map domain and routing errors to HTTP responses for the public API."""

from __future__ import annotations

import logging

from rest_framework.response import Response

from route_planner.services.route_planner import RoutePlanNotFeasibleError, RoutePlannerValidationError
from route_planner.services.routing.base import (
    GeocodingError,
    GeocodingNotFoundError,
    GeocodingOutsideUSAError,
    RouteError,
    RoutingAuthenticationError,
    RoutingBadRequestError,
    RoutingError,
    RoutingInvalidResponseError,
    RoutingNotFoundError,
    RoutingRateLimitError,
    RoutingServerError,
)
from route_planner.services.station_finder import InvalidRouteGeometryError

logger = logging.getLogger(__name__)

GENERIC_UPSTREAM_FAILURE = "The routing service could not complete this request."
GENERIC_UNAVAILABLE = "The routing service is temporarily unavailable."


def error_response(*, detail: str, status: int) -> Response:
    return Response({"detail": detail}, status=status)


def response_for_planning_exception(exc: BaseException) -> Response | None:
    if isinstance(exc, RoutePlannerValidationError):
        return error_response(detail=str(exc), status=400)

    if isinstance(exc, RoutePlanNotFeasibleError):
        return error_response(
            detail="The route cannot be completed with available fuel stations and vehicle range.",
            status=422,
        )

    if isinstance(exc, GeocodingOutsideUSAError):
        return error_response(
            detail="Location must resolve within the United States.",
            status=400,
        )

    if isinstance(exc, GeocodingNotFoundError):
        return error_response(
            detail="Could not resolve one or more locations.",
            status=400,
        )

    if isinstance(exc, GeocodingError):
        return error_response(
            detail="Could not resolve one or more locations.",
            status=400,
        )

    if isinstance(exc, RoutingBadRequestError):
        return error_response(
            detail="The routing service rejected this request.",
            status=400,
        )

    if isinstance(exc, RoutingNotFoundError):
        return error_response(
            detail="No driving route is available between these locations.",
            status=404,
        )

    if isinstance(exc, RoutingRateLimitError):
        return error_response(
            detail="The routing service rate limit was exceeded. Try again later.",
            status=429,
        )

    if isinstance(exc, RoutingServerError):
        logger.warning("Routing provider server error", exc_info=exc)
        return error_response(detail=GENERIC_UNAVAILABLE, status=503)

    if isinstance(exc, (RoutingInvalidResponseError, RoutingAuthenticationError)):
        logger.error("Routing provider integration failure", exc_info=exc)
        return error_response(detail=GENERIC_UPSTREAM_FAILURE, status=502)

    if isinstance(exc, RouteError):
        logger.warning("Routing failure", exc_info=exc)
        return error_response(detail=GENERIC_UPSTREAM_FAILURE, status=502)

    if isinstance(exc, RoutingError):
        logger.warning("Routing failure", exc_info=exc)
        return error_response(detail=GENERIC_UPSTREAM_FAILURE, status=502)

    if isinstance(exc, InvalidRouteGeometryError):
        logger.error("Invalid route geometry from provider", exc_info=exc)
        return error_response(detail=GENERIC_UPSTREAM_FAILURE, status=502)

    if isinstance(exc, ValueError):
        return error_response(detail=str(exc), status=400)

    return None
