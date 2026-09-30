from django.conf import settings

from route_planner.services.routing.open_route_service import OpenRouteServiceProvider


def get_routing_provider() -> OpenRouteServiceProvider:
    return OpenRouteServiceProvider(
        base_url=settings.ORS_BASE_URL,
        api_key=settings.ORS_API_KEY,
        geocode_cache_timeout_seconds=settings.ROUTE_CACHE_TIMEOUT_SECONDS,
        connect_timeout_seconds=settings.ORS_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=settings.ORS_READ_TIMEOUT_SECONDS,
    )
