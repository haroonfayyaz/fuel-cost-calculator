from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import CheckConstraint
from django.utils import timezone

from route_planner.models import FuelStation, US_STATE_CODES


@pytest.fixture
def station_kwargs():
    return {
        "opis_truckstop_id": "7",
        "name": "WOODSHED OF BIG CABIN",
        "address": "I-44, EXIT 283 & US-69",
        "city": "Big Cabin",
        "state": "OK",
        "rack_id": "307",
        "retail_price": Decimal("3.007333"),
        "source_line_number": 2,
    }


@pytest.mark.django_db
def test_retail_price_stored_as_decimal(station_kwargs):
    station = FuelStation.objects.create(**station_kwargs)
    station.refresh_from_db()
    assert station.retail_price == Decimal("3.007333")


@pytest.mark.django_db
def test_location_nullable_before_geocoding(station_kwargs):
    station = FuelStation.objects.create(**station_kwargs)
    assert station.location is None
    assert station.geocoding_status == FuelStation.GeocodingStatus.PENDING


@pytest.mark.django_db
def test_geocoded_station_has_point(station_kwargs):
    station = FuelStation.objects.create(**station_kwargs)
    station.location = Point(-95.5, 36.5, srid=4326)
    station.geocoding_status = FuelStation.GeocodingStatus.MATCHED
    station.geocoded_at = timezone.now()
    station.save()
    station.refresh_from_db()
    assert station.location.srid == 4326
    assert station.geocoding_status == FuelStation.GeocodingStatus.MATCHED


@pytest.mark.django_db
def test_retail_price_must_be_positive(station_kwargs):
    station = FuelStation(**{**station_kwargs, "retail_price": Decimal("0")})
    with pytest.raises(ValidationError):
        station.full_clean()


@pytest.mark.django_db
def test_retail_price_check_constraint_enforced(station_kwargs):
    station = FuelStation.objects.create(**station_kwargs)
    with pytest.raises(IntegrityError):
        FuelStation.objects.filter(pk=station.pk).update(retail_price=Decimal("-1"))


@pytest.mark.django_db
def test_physical_station_unique_constraint(station_kwargs):
    FuelStation.objects.create(**station_kwargs)
    with pytest.raises(IntegrityError):
        FuelStation.objects.create(
            **{
                **station_kwargs,
                "source_line_number": 3,
                "name": "Duplicate physical stop",
            }
        )


@pytest.mark.django_db
def test_opis_id_not_unique_across_different_locations(station_kwargs):
    FuelStation.objects.create(**station_kwargs)
    FuelStation.objects.create(
        **{
            **station_kwargs,
            "source_line_number": 3,
            "address": "Different Address",
            "retail_price": Decimal("3.100000"),
        }
    )
    assert FuelStation.objects.filter(opis_truckstop_id="7").count() == 2


@pytest.mark.django_db
def test_meta_has_spatial_and_price_constraints():
    constraint_names = {c.name for c in FuelStation._meta.constraints}
    assert "fuelstation_retail_price_range" in constraint_names
    assert "fuelstation_physical_station_uniq" in constraint_names
    price_constraint = next(
        c for c in FuelStation._meta.constraints if c.name == "fuelstation_retail_price_range"
    )
    assert isinstance(price_constraint, CheckConstraint)

    index_names = {i.name for i in FuelStation._meta.indexes}
    assert "fuelstation_location_gist" in index_names


@pytest.mark.django_db
def test_us_only_queryset(station_kwargs):
    FuelStation.objects.create(**station_kwargs)
    FuelStation.objects.create(
        **{
            **station_kwargs,
            "source_line_number": 99,
            "state": "ON",
            "city": "Toronto",
        }
    )
    assert FuelStation.objects.us_only().count() == 1


@pytest.mark.django_db
def test_pending_geocoding_queryset(station_kwargs):
    FuelStation.objects.create(**station_kwargs)
    assert FuelStation.objects.pending_geocoding().count() == 1


@pytest.mark.django_db
def test_str_representation(station_kwargs):
    station = FuelStation(**station_kwargs)
    assert "Big Cabin" in str(station)
    assert "OK" in str(station)


def test_us_state_codes_include_ok():
    assert "OK" in US_STATE_CODES
