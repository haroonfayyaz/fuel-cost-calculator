# Generated manually for physical-station uniqueness and import idempotency.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("route_planner", "0001_fuelstation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fuelstation",
            name="source_line_number",
            field=models.PositiveIntegerField(
                help_text="1-based CSV line number of the canonical row selected on import.",
            ),
        ),
        migrations.AddConstraint(
            model_name="fuelstation",
            constraint=models.UniqueConstraint(
                fields=("opis_truckstop_id", "address", "city", "state"),
                name="fuelstation_physical_station_uniq",
            ),
        ),
    ]
