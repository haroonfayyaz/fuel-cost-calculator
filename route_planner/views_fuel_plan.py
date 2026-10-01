"""HTTP view for fuel-efficient route planning."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from route_planner.api_errors import response_for_planning_exception
from route_planner.serializers import (
    FuelPlanRequestSerializer,
    FuelPlanResponseSerializer,
    build_fuel_plan_response_data,
)
from route_planner.services.route_planner import RoutePlanner
from route_planner.services.routing.factory import get_routing_provider


def get_route_planner() -> RoutePlanner:
    return RoutePlanner(get_routing_provider())


class FuelPlanView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=["Routes"],
        summary="Plan a fuel-efficient driving route",
        description=(
            "Computes a U.S. driving route, finds fuel stations along the corridor, "
            "and returns a refueling plan. Each endpoint must be either a location string "
            "or an object with `latitude` and `longitude`."
        ),
        request=FuelPlanRequestSerializer,
        responses={
            200: FuelPlanResponseSerializer,
            400: {"description": "Invalid request or location."},
            404: {"description": "No driving route available."},
            422: {"description": "Route cannot be completed with available fuel stations."},
            429: {"description": "Routing provider rate limit exceeded."},
            502: {"description": "Upstream routing provider failure."},
            503: {"description": "Routing provider temporarily unavailable."},
        },
        examples=[
            OpenApiExample(
                "Text locations",
                value={"start": "Dallas, TX", "finish": "Los Angeles, CA"},
                request_only=True,
            ),
            OpenApiExample(
                "Coordinates",
                value={
                    "start": {"latitude": 32.7767, "longitude": -96.797},
                    "finish": {"latitude": 34.0522, "longitude": -118.2437},
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = FuelPlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        planner = get_route_planner()
        try:
            result = planner.plan(serializer.to_route_plan_request())
        except Exception as exc:
            response = response_for_planning_exception(exc)
            if response is not None:
                return response
            raise

        return Response(
            build_fuel_plan_response_data(result),
            status=status.HTTP_200_OK,
        )
