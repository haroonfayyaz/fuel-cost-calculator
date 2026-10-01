from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from route_planner.models import FuelStation, US_STATE_CODES
from route_planner.services.fuel_import import (
    collapse_physical_duplicates,
    parse_csv_row,
    read_csv_rows,
    select_canonical_row,
)
from route_planner.services.import_runner import import_fuel_prices_from_csv

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.django_db
def test_canadian_stations_are_ignored():
    summary = import_fuel_prices_from_csv(FIXTURES / "mixed_us_ca.csv")
    assert summary.skipped_non_us == 1
    assert summary.us_rows == 2
    assert FuelStation.objects.count() == 2
    assert not FuelStation.objects.filter(state="ON").exists()


@pytest.mark.django_db
def test_us_rows_are_limited_to_us_state_codes():
    import_fuel_prices_from_csv(FIXTURES / "mixed_us_ca.csv")
    states = set(FuelStation.objects.values_list("state", flat=True))
    assert states
    assert states.issubset(set(US_STATE_CODES))


@pytest.mark.django_db
def test_invalid_prices_are_ignored():
    summary = import_fuel_prices_from_csv(FIXTURES / "invalid_prices.csv")
    assert summary.invalid_rows == 3
    assert FuelStation.objects.count() == 1
    station = FuelStation.objects.get()
    assert station.retail_price == Decimal("3.250000")


@pytest.mark.django_db
def test_duplicate_import_is_idempotent():
    path = FIXTURES / "mixed_us_ca.csv"
    first = import_fuel_prices_from_csv(path)
    second = import_fuel_prices_from_csv(path)
    assert first.created == 2
    assert second.created == 0
    assert second.updated == 0
    assert FuelStation.objects.count() == 2


@pytest.mark.django_db
def test_same_price_physical_duplicates_create_one_station():
    summary = import_fuel_prices_from_csv(FIXTURES / "duplicate_same_price.csv")
    assert summary.us_rows == 2
    assert summary.duplicates_collapsed == 1
    assert FuelStation.objects.count() == 1


@pytest.mark.django_db
def test_conflicting_prices_use_lowest_price_deterministically():
    import_fuel_prices_from_csv(FIXTURES / "duplicate_conflicting_price.csv")
    station = FuelStation.objects.get()
    assert station.retail_price == Decimal("3.269000")
    assert station.name == "TA CENTER"


@pytest.mark.django_db
def test_update_existing_flag_updates_station():
    path = FIXTURES / "duplicate_conflicting_price.csv"
    import_fuel_prices_from_csv(path)

    updated_csv = FIXTURES / "duplicate_conflicting_price_updated.csv"
    updated_csv.write_text(
        "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
        "105,TA UPDATED,I-75 EXIT 144-B,Bridgeport,MI,260,3.100\n",
        encoding="utf-8",
    )
    try:
        summary = import_fuel_prices_from_csv(updated_csv, update_existing=True)
        assert summary.updated == 1
        station = FuelStation.objects.get()
        assert station.name == "TA UPDATED"
        assert station.retail_price == Decimal("3.100000")
    finally:
        updated_csv.unlink(missing_ok=True)


@pytest.mark.django_db
def test_dry_run_does_not_write():
    before = FuelStation.objects.count()
    summary = import_fuel_prices_from_csv(FIXTURES / "mixed_us_ca.csv", dry_run=True)
    assert summary.created == 0
    assert FuelStation.objects.count() == before


def test_select_canonical_row_prefers_lowest_price():
    rows = [
        parse_csv_row(
            {
                "OPIS Truckstop ID": "1",
                "Truckstop Name": "A",
                "Address": "Addr",
                "City": "City",
                "State": "TX",
                "Rack ID": "1",
                "Retail Price": "3.50",
            },
            2,
        ),
        parse_csv_row(
            {
                "OPIS Truckstop ID": "1",
                "Truckstop Name": "B",
                "Address": "Addr",
                "City": "City",
                "State": "TX",
                "Rack ID": "1",
                "Retail Price": "3.10",
            },
            3,
        ),
    ]
    canonical = select_canonical_row([row for row in rows if row is not None])
    assert canonical.retail_price == Decimal("3.10")


def test_collapse_physical_duplicates_count():
    rows, _ = read_csv_rows(FIXTURES / "duplicate_same_price.csv")
    parsed = [parse_csv_row(row, index) for index, row in enumerate(rows, start=2)]
    us_rows = [row for row in parsed if row is not None]
    canonical, collapsed = collapse_physical_duplicates(us_rows)
    assert len(canonical) == 1
    assert collapsed == 1


@pytest.mark.django_db
def test_management_command_prints_summary(capsys):
    call_command("import_fuel_prices", str(FIXTURES / "mixed_us_ca.csv"))
    output = capsys.readouterr().out
    assert "Total CSV rows: 3" in output
    assert "Skipped non-U.S.: 1" in output


def test_management_command_missing_file():
    with pytest.raises(CommandError):
        call_command("import_fuel_prices", "does-not-exist.csv")
