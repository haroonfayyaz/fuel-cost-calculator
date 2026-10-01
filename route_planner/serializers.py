"""DRF serializers for the fuel route planning API."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from route_planner.services.route_planner import RouteLocationInput, RoutePlanRequest


class CoordinateLocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90.0, max_value=90.0)
    longitude = serializers.FloatField(min_value=-180.0, max_value=180.0)


class LocationInputField(serializers.Field):
    """Accept a non-empty string or a coordinate object with latitude and longitude."""

    default_error_messages = {
        "invalid_type": "Expected a location string or an object with latitude and longitude.",
        "blank": "Location text must not be blank.",
        "invalid_object": "Invalid location object.",
    }

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not text:
                self.fail("blank")
            return RouteLocationInput(text=text)

        if isinstance(data, dict):
            serializer = CoordinateLocationSerializer(data=data)
            if not serializer.is_valid():
                raise serializers.ValidationError(serializer.errors)
            validated = serializer.validated_data
            return RouteLocationInput(
                latitude=validated["latitude"],
                longitude=validated["longitude"],
            )

        self.fail("invalid_type")

    def to_representation(self, value):
        if value.text is not None:
            return value.text
        return {"latitude": value.latitude, "longitude": value.longitude}


class FuelPlanRequestSerializer(serializers.Serializer):
    start = LocationInputField()
    finish = LocationInputField()

    def create(self, validated_data):
        raise NotImplementedError

    def update(self, instance, validated_data):
        raise NotImplementedError

    def to_route_plan_request(self) -> RoutePlanRequest:
        if not hasattr(self, "_validated_data"):
            raise AssertionError("Call is_valid() before building RoutePlanRequest.")
        return RoutePlanRequest(
            start=self.validated_data["start"],
            finish=self.validated_data["finish"],
        )


def _decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class FuelPlanFuelStopSerializer(serializers.Serializer):
    station_id = serializers.IntegerField()
    station_name = serializers.CharField()
    address = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    route_mile = serializers.FloatField()
    price_per_gallon = serializers.CharField()
    gallons_purchased = serializers.CharField()
    fuel_cost = serializers.CharField()


class FuelPlanVehicleSerializer(serializers.Serializer):
    mpg = serializers.IntegerField()
    maximum_range_miles = serializers.IntegerField()
    tank_capacity_gallons = serializers.CharField()


class FuelPlanAssumptionsSerializer(serializers.Serializer):
    starts_with_full_tank = serializers.BooleanField()
    starting_fuel_cost_included = serializers.BooleanField()


class FuelPlanResponseSerializer(serializers.Serializer):
    route = serializers.DictField()
    distance_miles = serializers.FloatField()
    duration_seconds = serializers.FloatField()
    vehicle = FuelPlanVehicleSerializer()
    fuel_stops = FuelPlanFuelStopSerializer(many=True)
    fuel_consumed_gallons = serializers.CharField()
    fuel_purchased_gallons = serializers.CharField()
    total_fuel_cost = serializers.CharField()
    assumptions = FuelPlanAssumptionsSerializer()


def build_fuel_plan_response_data(result) -> dict:
    """Map ``RoutePlanResult`` to the public JSON shape."""
    from route_planner.services.route_planner import RoutePlanResult

    if not isinstance(result, RoutePlanResult):
        raise TypeError("Expected RoutePlanResult.")

    geometry = result.route.geometry
    fuel_stops = [
        {
            "station_id": stop.station_id,
            "station_name": stop.name,
            "address": stop.address,
            "latitude": stop.latitude,
            "longitude": stop.longitude,
            "route_mile": float(stop.route_mile),
            "price_per_gallon": _decimal_string(stop.price_per_gallon),
            "gallons_purchased": _decimal_string(stop.gallons_purchased),
            "fuel_cost": _decimal_string(stop.cost),
        }
        for stop in result.fuel_stops
    ]

    return {
        "route": {
            "type": geometry.get("type"),
            "coordinates": geometry.get("coordinates", []),
        },
        "distance_miles": result.route.distance_miles,
        "duration_seconds": result.route.duration_seconds,
        "vehicle": {
            "mpg": result.vehicle.mpg,
            "maximum_range_miles": result.vehicle.maximum_range_miles,
            "tank_capacity_gallons": _decimal_string(result.vehicle.tank_capacity_gallons),
        },
        "fuel_stops": fuel_stops,
        "fuel_consumed_gallons": _decimal_string(result.fuel_consumed_gallons),
        "fuel_purchased_gallons": _decimal_string(result.fuel_purchased_gallons),
        "total_fuel_cost": _decimal_string(result.total_fuel_cost),
        "assumptions": {
            "starts_with_full_tank": result.assumptions.starts_with_full_tank,
            "starting_fuel_cost_included": result.assumptions.starting_fuel_cost_included,
        },
    }
