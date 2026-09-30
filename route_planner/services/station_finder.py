"""
Find geocoded fuel stations near a driving route using PostGIS.

Spatial strategy (single database query, no Python-side filtering of the full table):

1. ``ST_SetSRID(ST_GeomFromEWKT(...), 4326)::geography`` — route polyline in WGS84 as geography
   so distances are measured in meters on the spheroid, not in degrees.

2. ``ST_DWithin(station::geography, route::geography, radius_meters)`` — index-friendly corridor
   filter (uses the station ``location`` GiST index when combined with other predicates).

3. ``ST_LineLocatePoint(route, station)`` — fraction in [0, 1] along the line from start to finish.

4. ``ST_Distance(station::geography, route::geography)`` — shortest geodesic distance from the
   station to the route polyline (meters), converted to miles for reporting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, LineString
from django.db.models.expressions import RawSQL

from route_planner.models import FuelStation

METERS_PER_MILE = 1609.344


class InvalidRouteGeometryError(ValueError):
    """Raised when route GeoJSON cannot be converted to a valid LineString."""


@dataclass(frozen=True)
class CandidateFuelStation:
    station_id: int
    name: str
    address: str
    latitude: float
    longitude: float
    retail_price: Decimal
    route_fraction: float
    route_mile: float
    distance_from_route_miles: float


def geojson_to_linestring(geometry: dict[str, Any]) -> LineString:
    if geometry.get("type") != "LineString":
        raise InvalidRouteGeometryError("Route geometry must be a GeoJSON LineString.")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise InvalidRouteGeometryError("LineString must contain at least two coordinates.")

    geos = GEOSGeometry(json.dumps(geometry), srid=4326)
    if not isinstance(geos, LineString):
        raise InvalidRouteGeometryError("Route geometry did not produce a LineString.")
    if geos.srid != 4326:
        geos.srid = 4326
    return geos


def find_stations_near_route(
    route_geometry: dict[str, Any],
    route_distance_miles: float,
    *,
    corridor_radius_miles: float | Decimal | None = None,
) -> list[CandidateFuelStation]:
    if route_distance_miles <= 0:
        raise ValueError("route_distance_miles must be positive.")

    if corridor_radius_miles is None:
        corridor_radius_miles = float(settings.ROUTE_STATION_CORRIDOR_MILES)
    corridor_meters = float(corridor_radius_miles) * METERS_PER_MILE

    route_line = geojson_to_linestring(route_geometry)
    route_ewkt = route_line.ewkt

    route_geom_sql = "ST_SetSRID(ST_GeomFromEWKT(%s), 4326)"
    route_geog_sql = f"{route_geom_sql}::geography"

    queryset = (
        FuelStation.objects.geocoded()
        .us_only()
        .filter(retail_price__gt=0)
        .extra(
            where=[
                f"ST_DWithin(location::geography, {route_geog_sql}, %s)",
            ],
            params=[route_ewkt, corridor_meters],
        )
        .annotate(
            route_fraction=RawSQL(
                f"ST_LineLocatePoint({route_geom_sql}, location)",
                (route_ewkt,),
            ),
            distance_from_route_meters=RawSQL(
                f"ST_Distance(location::geography, {route_geog_sql})",
                (route_ewkt,),
            ),
        )
        .order_by("route_fraction")
    )

    candidates: list[CandidateFuelStation] = []
    for station in queryset:
        fraction = float(station.route_fraction)
        distance_meters = float(station.distance_from_route_meters)
        candidates.append(
            CandidateFuelStation(
                station_id=station.pk,
                name=station.name,
                address=station.address,
                latitude=station.location.y,
                longitude=station.location.x,
                retail_price=station.retail_price,
                route_fraction=fraction,
                route_mile=fraction * route_distance_miles,
                distance_from_route_miles=distance_meters / METERS_PER_MILE,
            )
        )
    return candidates
