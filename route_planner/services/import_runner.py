from __future__ import annotations

from pathlib import Path

from django.db import transaction

from route_planner.models import FuelStation
from route_planner.services.fuel_import import (
    ImportSummary,
    collapse_physical_duplicates,
    parse_csv_row,
    partition_us_rows,
    read_csv_rows,
)


def import_fuel_prices_from_csv(
    csv_path: Path,
    *,
    dry_run: bool = False,
    update_existing: bool = False,
) -> ImportSummary:
    raw_rows, _ = read_csv_rows(csv_path)
    summary = ImportSummary(total_csv_rows=len(raw_rows))

    parsed: list = []
    for index, row in enumerate(raw_rows, start=2):
        parsed.append(parse_csv_row(row, source_line_number=index))

    us_rows, skipped_non_us, invalid_rows = partition_us_rows(parsed)
    summary.us_rows = len(us_rows)
    summary.skipped_non_us = skipped_non_us
    summary.invalid_rows = invalid_rows

    canonical_rows, collapsed = collapse_physical_duplicates(us_rows)
    summary.duplicates_collapsed = collapsed

    if dry_run:
        summary.total_stations_in_db = FuelStation.objects.count()
        return summary

    with transaction.atomic():
        for row in canonical_rows:
            defaults = {
                "name": row.name,
                "rack_id": row.rack_id,
                "retail_price": row.retail_price,
                "source_line_number": row.source_line_number,
                "geocoding_status": FuelStation.GeocodingStatus.PENDING,
            }
            lookup = {
                "opis_truckstop_id": row.opis_truckstop_id,
                "address": row.address,
                "city": row.city,
                "state": row.state,
            }

            existing = FuelStation.objects.filter(**lookup).first()
            if existing is None:
                FuelStation.objects.create(**lookup, **defaults)
                summary.created += 1
                continue

            if update_existing:
                for field, value in {**lookup, **defaults}.items():
                    setattr(existing, field, value)
                existing.save()
                summary.updated += 1

        summary.total_stations_in_db = FuelStation.objects.count()

    return summary
