import json
from unittest.mock import MagicMock

import pytest
import requests
from django.core.cache import cache

from route_planner.services.routing.base import (
    GeocodingNotFoundError,
    GeocodingOutsideUSAError,
    RoutePoint,
    RoutingAuthenticationError,
    RoutingBadRequestError,
    RoutingInvalidResponseError,
    RoutingRateLimitError,
    RoutingServerError,
)
from route_planner.services.routing.open_route_service import OpenRouteServiceProvider


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def provider():
    session = MagicMock()
    return OpenRouteServiceProvider(
        base_url="https://api.heigit.org",
        api_key="test-api-key",
        geocode_cache_timeout_seconds=3600,
        route_cache_timeout_seconds=3600,
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
        session=session,
    ), session


def _directions_post_calls(session):
    return [
        call
        for call in session.request.call_args_list
        if call.kwargs.get("method") == "POST"
        and "directions" in call.kwargs.get("url", "")
    ]


def _response(status_code: int, payload: dict | str):
    response = MagicMock()
    response.status_code = status_code
    if isinstance(payload, dict):
        response.json.return_value = payload
        response.text = json.dumps(payload)
    else:
        response.json.side_effect = json.JSONDecodeError("bad", payload, 0)
        response.text = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def test_geocode_sends_usa_restriction(provider):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {"coordinates": [-104.9903, 39.7392]},
                    "properties": {
                        "label": "Denver, CO, USA",
                        "country_code": "US",
                    },
                }
            ]
        },
    )

    result = client.geocode_location("Denver, CO")

    assert result.latitude == pytest.approx(39.7392)
    assert result.longitude == pytest.approx(-104.9903)
    assert result.formatted_address == "Denver, CO, USA"
    session.request.assert_called_once()
    call_kwargs = session.request.call_args.kwargs
    assert call_kwargs["params"]["boundary.country"] == "USA"
    assert call_kwargs["headers"]["Authorization"] == "test-api-key"
    assert call_kwargs["headers"]["Accept"] == "application/json"


def test_geocode_caches_by_normalized_input(provider):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {"coordinates": [-97.7431, 30.2672]},
                    "properties": {
                        "label": "Austin, TX, USA",
                        "country_code": "US",
                    },
                }
            ]
        },
    )

    first = client.geocode_location("  Austin,   TX ")
    second = client.geocode_location("austin, tx")

    assert first == second
    assert session.request.call_count == 1


def test_geocode_rejects_non_us_result(provider):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {"coordinates": [-79.3832, 43.6532]},
                    "properties": {
                        "label": "Toronto, ON, Canada",
                        "country_code": "CA",
                    },
                }
            ]
        },
    )

    with pytest.raises(GeocodingOutsideUSAError):
        client.geocode_location("Toronto, Canada")


def test_geocode_no_results(provider):
    client, session = provider
    session.request.return_value = _response(200, {"features": []})

    with pytest.raises(GeocodingNotFoundError):
        client.geocode_location("Nowhere")


def test_get_route_makes_exactly_one_directions_request(provider):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-105.0, 39.7], [-104.9, 39.8]],
                    },
                    "properties": {"summary": {"distance": 16093.4, "duration": 900.0}},
                }
            ]
        },
    )

    start = RoutePoint(latitude=39.7, longitude=-105.0)
    finish = RoutePoint(latitude=39.8, longitude=-104.9)
    result = client.get_route(start, finish)

    assert session.request.call_count == 1
    call_kwargs = session.request.call_args.kwargs
    assert call_kwargs["method"] == "POST"
    assert "openrouteservice/v2/directions/driving-car/geojson" in call_kwargs["url"]
    assert call_kwargs["headers"]["Accept"] == "application/geo+json"
    assert call_kwargs["json"]["coordinates"] == [
        [-105.0, 39.7],
        [-104.9, 39.8],
    ]
    assert result.total_distance_meters == pytest.approx(16093.4)
    assert result.duration_seconds == pytest.approx(900.0)
    assert result.total_distance_miles == pytest.approx(16093.4 * 0.000621371)
    assert result.geometry["type"] == "LineString"


def test_get_route_caches_identical_endpoints(provider):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[-105.0, 39.7], [-104.9, 39.8]]},
                    "properties": {"summary": {"distance": 16093.4, "duration": 900.0}},
                }
            ]
        },
    )
    start = RoutePoint(latitude=39.7392, longitude=-104.9903)
    finish = RoutePoint(latitude=39.8, longitude=-104.9)

    first = client.get_route(start, finish)
    second = client.get_route(start, finish)

    assert first.total_distance_meters == second.total_distance_meters
    assert len(_directions_post_calls(session)) == 1


def test_get_route_different_endpoints_do_not_share_cache(provider):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[-105.0, 39.7], [-104.9, 39.8]]},
                    "properties": {"summary": {"distance": 16093.4, "duration": 900.0}},
                }
            ]
        },
    )

    client.get_route(RoutePoint(39.7, -105.0), RoutePoint(39.8, -104.9))
    client.get_route(RoutePoint(39.7002, -105.0), RoutePoint(39.8, -104.9))

    assert len(_directions_post_calls(session)) == 2


def test_get_route_survives_cache_read_failure(provider, monkeypatch):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[-105.0, 39.7]]},
                    "properties": {"summary": {"distance": 100.0, "duration": 10.0}},
                }
            ]
        },
    )

    def boom(_key, *_args, **_kwargs):
        raise OSError("cache down")

    monkeypatch.setattr(
        "route_planner.services.routing.routing_cache.cache.get",
        boom,
    )

    result = client.get_route(RoutePoint(39.7, -105.0), RoutePoint(39.8, -104.9))
    assert result.total_distance_meters == pytest.approx(100.0)
    assert len(_directions_post_calls(session)) == 1


def test_get_route_longitude_latitude_ordering(provider):
    client, session = provider
    session.request.return_value = _response(
        200,
        {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[1.0, 2.0]]},
                    "properties": {"summary": {"distance": 100.0, "duration": 10.0}},
                }
            ]
        },
    )

    client.get_route(
        RoutePoint(latitude=10.5, longitude=-20.25),
        RoutePoint(latitude=11.0, longitude=-21.0),
    )

    coordinates = session.request.call_args.kwargs["json"]["coordinates"]
    assert coordinates[0] == [-20.25, 10.5]
    assert coordinates[1] == [-21.0, 11.0]


def test_routing_errors_map_to_application_exceptions(provider):
    client, session = provider

    session.request.return_value = _response(400, {"error": "bad request"})
    with pytest.raises(RoutingBadRequestError):
        client.get_route(RoutePoint(1.0, 1.0), RoutePoint(2.0, 2.0))

    session.request.return_value = _response(401, {"error": "unauthorized"})
    with pytest.raises(RoutingAuthenticationError):
        client.get_route(RoutePoint(1.0, 1.0), RoutePoint(2.0, 2.0))

    session.request.return_value = _response(429, {"error": "rate limit"})
    with pytest.raises(RoutingRateLimitError):
        client.get_route(RoutePoint(1.0, 1.0), RoutePoint(2.0, 2.0))

    session.request.return_value = _response(500, {"error": "server"})
    with pytest.raises(RoutingServerError):
        client.get_route(RoutePoint(1.0, 1.0), RoutePoint(2.0, 2.0))

    session.request.return_value = _response(200, "not-json")
    with pytest.raises(RoutingInvalidResponseError):
        client.get_route(RoutePoint(1.0, 1.0), RoutePoint(2.0, 2.0))
