"""CSV parsing and normalization for fuel station imports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from route_planner.models import US_STATE_CODES

REQUIRED_CSV_COLUMNS = (
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
)


@dataclass(frozen=True)
class ParsedFuelRow:
    source_line_number: int
    opis_truckstop_id: str
    name: str
    address: str
    city: str
    state: str
    rack_id: str
    retail_price: Decimal

    @property
    def physical_station_key(self) -> tuple[str, str, str, str]:
        return (
            self.opis_truckstop_id,
            self.address,
            self.city,
            self.state,
        )


@dataclass
class ImportSummary:
    total_csv_rows: int = 0
    us_rows: int = 0
    skipped_non_us: int = 0
    created: int = 0
    updated: int = 0
    duplicates_collapsed: int = 0
    invalid_rows: int = 0
    total_stations_in_db: int = 0

    def as_text(self) -> str:
        return (
            f"Total CSV rows: {self.total_csv_rows}\n"
            f"U.S. rows: {self.us_rows}\n"
            f"Skipped non-U.S.: {self.skipped_non_us}\n"
            f"Created: {self.created}\n"
            f"Updated: {self.updated}\n"
            f"Duplicates collapsed: {self.duplicates_collapsed}\n"
            f"Invalid rows: {self.invalid_rows}\n"
            f"Total stations in DB: {self.total_stations_in_db}\n"
        )


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_state(value: str) -> str:
    return normalize_whitespace(value).upper()


def normalize_city(value: str) -> str:
    return normalize_whitespace(value).title()


def normalize_address(value: str) -> str:
    return normalize_whitespace(value)


def normalize_name(value: str) -> str:
    return normalize_whitespace(value)


def parse_retail_price(raw: str) -> Decimal | None:
    text = raw.strip()
    if not text:
        return None
    try:
        price = Decimal(text)
    except InvalidOperation:
        return None
    if price <= 0 or price > Decimal("99.999999"):
        return None
    return price


def validate_csv_headers(fieldnames: list[str] | None) -> None:
    if not fieldnames:
        raise ValueError("CSV file is empty or missing a header row.")
    missing = [column for column in REQUIRED_CSV_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(missing)}")


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        validate_csv_headers(reader.fieldnames)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def parse_csv_row(row: dict[str, str], source_line_number: int) -> ParsedFuelRow | None:
    opis_id = normalize_whitespace(row["OPIS Truckstop ID"])
    name = normalize_name(row["Truckstop Name"])
    address = normalize_address(row["Address"])
    city = normalize_city(row["City"])
    state = normalize_state(row["State"])
    rack_id = normalize_whitespace(row["Rack ID"])
    retail_price = parse_retail_price(row["Retail Price"])

    if not opis_id or not name or not address or not city or not state or not rack_id:
        return None
    if retail_price is None:
        return None
    if len(state) != 2:
        return None

    return ParsedFuelRow(
        source_line_number=source_line_number,
        opis_truckstop_id=opis_id,
        name=name,
        address=address,
        city=city,
        state=state,
        rack_id=rack_id,
        retail_price=retail_price,
    )


def select_canonical_row(rows: list[ParsedFuelRow]) -> ParsedFuelRow:
    """
    De-duplication policy for one physical station (same OPIS ID + address + city + state):

    1. Keep the row with the lowest retail price (fuel-cost optimizer uses cheapest listed price).
    2. If prices tie, keep the row with the lowest source_line_number (earliest row in the CSV).
    """
    return min(rows, key=lambda row: (row.retail_price, row.source_line_number))


def collapse_physical_duplicates(rows: list[ParsedFuelRow]) -> tuple[list[ParsedFuelRow], int]:
    grouped: dict[tuple[str, str, str, str], list[ParsedFuelRow]] = {}
    for row in rows:
        grouped.setdefault(row.physical_station_key, []).append(row)

    canonical_rows = [select_canonical_row(group) for group in grouped.values()]
    collapsed = sum(len(group) - 1 for group in grouped.values())
    return canonical_rows, collapsed


def partition_us_rows(
    parsed_rows: list[ParsedFuelRow | None],
) -> tuple[list[ParsedFuelRow], int, int]:
    us_rows: list[ParsedFuelRow] = []
    skipped_non_us = 0
    invalid_rows = 0

    for row in parsed_rows:
        if row is None:
            invalid_rows += 1
            continue
        if row.state not in US_STATE_CODES:
            skipped_non_us += 1
            continue
        us_rows.append(row)

    return us_rows, skipped_non_us, invalid_rows
