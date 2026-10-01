from decimal import Decimal

from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GistIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q

US_STATE_CODES = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    }
)


class FuelStationQuerySet(models.QuerySet):
    def us_only(self):
        return self.filter(state__in=US_STATE_CODES)

    def pending_geocoding(self):
        return self.us_only().filter(
            geocoding_status=FuelStation.GeocodingStatus.PENDING,
            location__isnull=True,
        )

    def geocoded(self):
        return self.filter(
            geocoding_status=FuelStation.GeocodingStatus.MATCHED,
            location__isnull=False,
        )


class FuelStation(models.Model):
    class GeocodingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        MATCHED = "matched", "Matched"
        UNMATCHED = "unmatched", "Unmatched"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    opis_truckstop_id = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=512)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.CharField(max_length=32)
    retail_price = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("0.000001")),
            MaxValueValidator(Decimal("99.999999")),
        ],
    )
    location = models.PointField(srid=4326, geography=False, null=True, blank=True)
    geocoding_status = models.CharField(
        max_length=16,
        choices=GeocodingStatus.choices,
        default=GeocodingStatus.PENDING,
    )
    geocoded_at = models.DateTimeField(null=True, blank=True)
    source_line_number = models.PositiveIntegerField(
        help_text="1-based CSV line number of the canonical row selected on import.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = FuelStationQuerySet.as_manager()

    class Meta:
        indexes = [
            GistIndex(fields=["location"], name="fuelstation_location_gist"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(retail_price__gt=0) & Q(retail_price__lte=Decimal("99.999999")),
                name="fuelstation_retail_price_range",
            ),
            models.UniqueConstraint(
                fields=["opis_truckstop_id", "address", "city", "state"],
                name="fuelstation_physical_station_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) — ${self.retail_price}"

    @property
    def physical_station_key(self) -> tuple[str, str, str, str]:
        """Stable key for one physical stop (multiple CSV rows may share this)."""
        return (
            self.opis_truckstop_id,
            self.address.strip(),
            self.city.strip(),
            self.state.strip(),
        )
