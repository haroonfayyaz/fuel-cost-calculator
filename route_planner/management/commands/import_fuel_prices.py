from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from route_planner.services.import_runner import import_fuel_prices_from_csv


class Command(BaseCommand):
    help = (
        "Import U.S. fuel stations from a CSV file. "
        "De-duplicates physical stations by OPIS ID + normalized address + city + state. "
        "When multiple prices exist for the same stop, the lowest retail price wins; "
        "ties use the earliest CSV line number."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to fuel-prices.csv")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and summarize without writing to the database.",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Update existing physical stations when CSV data changes.",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"])
        if not csv_path.is_file():
            raise CommandError(f"CSV file not found: {csv_path}")

        try:
            summary = import_fuel_prices_from_csv(
                csv_path,
                dry_run=options["dry_run"],
                update_existing=options["update_existing"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(summary.as_text())
