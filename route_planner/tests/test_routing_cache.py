"""Unit tests for routing cache key helpers."""

from route_planner.services.routing.base import RoutePoint
from route_planner.services.routing.routing_cache import (
    geocode_cache_key,
    normalize_geocode_query,
    route_cache_key,
    route_endpoint_cache_token,
)


def test_geocode_cache_key_uses_normalized_text_not_raw():
    assert geocode_cache_key(normalize_geocode_query("  Austin, TX ")) == geocode_cache_key(
        normalize_geocode_query("austin, tx")
    )


def test_route_cache_key_stable_for_rounded_coordinates():
    start = RoutePoint(latitude=32.7767123, longitude=-96.7970123)
    finish = RoutePoint(latitude=34.0522345, longitude=-118.2435678)
    key_a = route_cache_key(
        start,
        finish,
        profile="driving-car",
        version="1",
        decimal_places=4,
    )
    key_b = route_cache_key(
        RoutePoint(32.7767123, -96.7970123),
        RoutePoint(34.0522345, -118.2435678),
        profile="driving-car",
        version="1",
        decimal_places=4,
    )
    assert key_a == key_b


def test_route_cache_key_differs_for_materially_different_endpoints():
    start = RoutePoint(latitude=32.7767, longitude=-96.7970)
    finish_a = RoutePoint(latitude=34.0522, longitude=-118.2437)
    finish_b = RoutePoint(latitude=34.0524, longitude=-118.2437)
    key_a = route_cache_key(start, finish_a, profile="driving-car", version="1", decimal_places=4)
    key_b = route_cache_key(start, finish_b, profile="driving-car", version="1", decimal_places=4)
    assert key_a != key_b


def test_route_endpoint_cache_token_rounds_to_configured_precision():
    token = route_endpoint_cache_token(
        RoutePoint(latitude=10.123456, longitude=-20.987654),
        decimal_places=4,
    )
    assert token == "10.1235,-20.9877"
