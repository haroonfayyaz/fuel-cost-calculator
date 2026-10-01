from django.conf import settings

from route_planner.services.routing.open_route_service import OpenRouteServiceProvider


def get_routing_provider() -> OpenRouteServiceProvider:
    return OpenRouteServiceProvider(
        base_url=settings.ORS_BASE_URL,
        api_key=settings.ORS_API_KEY,
        geocode_cache_timeout_seconds=settings.ORS_GEOCODE_CACHE_TIMEOUT_SECONDS,
        route_cache_timeout_seconds=settings.ROUTE_CACHE_TIMEOUT_SECONDS,
        routing_profile=settings.ORS_ROUTING_PROFILE,
        routing_cache_version=settings.ORS_ROUTING_CACHE_VERSION,
        route_coordinate_cache_decimals=settings.ROUTE_COORDINATE_CACHE_DECIMALS,
        connect_timeout_seconds=settings.ORS_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=settings.ORS_READ_TIMEOUT_SECONDS,
    )
