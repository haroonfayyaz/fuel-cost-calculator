from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from route_planner.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(GISModelAdmin):
    list_display = (
        "name",
        "city",
        "state",
        "retail_price",
        "geocoding_status",
        "source_line_number",
    )
    list_filter = ("state", "geocoding_status")
    search_fields = ("name", "address", "city", "opis_truckstop_id")
    readonly_fields = ("created_at", "updated_at", "source_line_number")
