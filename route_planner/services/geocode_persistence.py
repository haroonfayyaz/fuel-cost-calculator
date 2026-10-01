"""Batch DB writes for long-running geocode jobs."""

from __future__ import annotations

from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

from route_planner.models import FuelStation

GEOCODE_UPDATE_FIELDS = [
    "location",
    "geocoding_status",
    "geocoded_at",
    "updated_at",
]


def apply_geocode_matched(station: FuelStation, location: Point, *, now=None) -> None:
    now = now or timezone.now()
    station.location = location
    station.geocoding_status = FuelStation.GeocodingStatus.MATCHED
    station.geocoded_at = now
    station.updated_at = now


def apply_geocode_unmatched(station: FuelStation, *, now=None) -> None:
    now = now or timezone.now()
    station.location = None
    station.geocoding_status = FuelStation.GeocodingStatus.UNMATCHED
    station.geocoded_at = now
    station.updated_at = now


def apply_geocode_failed(station: FuelStation, *, now=None) -> None:
    now = now or timezone.now()
    station.geocoding_status = FuelStation.GeocodingStatus.FAILED
    station.geocoded_at = now
    station.updated_at = now


class GeocodeWriteBuffer:
    """Accumulate row updates and flush with ``bulk_update`` (one query per batch)."""

    def __init__(self, batch_size: int = 100) -> None:
        self.batch_size = max(1, batch_size)
        self._pending: list[FuelStation] = []

    def stage(self, station: FuelStation) -> None:
        self._pending.append(station)
        if len(self._pending) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        with transaction.atomic():
            FuelStation.objects.bulk_update(self._pending, GEOCODE_UPDATE_FIELDS)
        self._pending.clear()

    def __enter__(self) -> GeocodeWriteBuffer:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.flush()
