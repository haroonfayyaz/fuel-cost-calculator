from django.db import migrations, models


def migrate_success_to_matched(apps, schema_editor):
    FuelStation = apps.get_model("route_planner", "FuelStation")
    FuelStation.objects.filter(geocoding_status="success").update(geocoding_status="matched")


class Migration(migrations.Migration):

    dependencies = [
        ("route_planner", "0002_physical_station_unique"),
    ]

    operations = [
        migrations.RunPython(migrate_success_to_matched, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="fuelstation",
            name="geocoding_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("matched", "Matched"),
                    ("unmatched", "Unmatched"),
                    ("failed", "Failed"),
                    ("skipped", "Skipped"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
    ]
