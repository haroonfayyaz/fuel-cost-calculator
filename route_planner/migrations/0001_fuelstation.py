import django.contrib.gis.db.models.fields
import django.core.validators
from decimal import Decimal

import django.contrib.postgres.indexes
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FuelStation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("opis_truckstop_id", models.CharField(db_index=True, max_length=32)),
                ("name", models.CharField(max_length=255)),
                ("address", models.CharField(max_length=512)),
                ("city", models.CharField(max_length=128)),
                ("state", models.CharField(db_index=True, max_length=2)),
                ("rack_id", models.CharField(max_length=32)),
                (
                    "retail_price",
                    models.DecimalField(
                        decimal_places=6,
                        max_digits=10,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("1E-6")),
                            django.core.validators.MaxValueValidator(Decimal("99.999999")),
                        ],
                    ),
                ),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, null=True, srid=4326
                    ),
                ),
                (
                    "geocoding_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("geocoded_at", models.DateTimeField(blank=True, null=True)),
                (
                    "source_line_number",
                    models.PositiveIntegerField(
                        help_text="1-based line number in data/fuel-prices.csv for traceability.",
                        unique=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("retail_price__gt", 0),
                            ("retail_price__lte", Decimal("99.999999")),
                        ),
                        name="fuelstation_retail_price_range",
                    ),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=django.contrib.postgres.indexes.GistIndex(
                fields=["location"],
                name="fuelstation_location_gist",
            ),
        ),
    ]
