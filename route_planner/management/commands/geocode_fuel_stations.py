from django.conf import settings
from django.core.management.base import BaseCommand

from route_planner.services.geocode_runner import run_geocode_job


class Command(BaseCommand):
    help = "Geocode FuelStation rows using the U.S. Census batch geocoder (offline preprocessing)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of stations to geocode in this run.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-geocode stations even when a location is already stored.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many stations would be processed without calling Census.",
        )

    def handle(self, *args, **options):
        summary = run_geocode_job(
            force=options["force"],
            limit=options["limit"],
            dry_run=options["dry_run"],
            batch_url=settings.CENSUS_GEOCODER_BATCH_URL,
            benchmark=settings.CENSUS_GEOCODER_BENCHMARK,
            batch_size=settings.CENSUS_GEOCODER_BATCH_SIZE,
            timeout_seconds=settings.CENSUS_GEOCODER_TIMEOUT_SECONDS,
            max_retries=settings.CENSUS_GEOCODER_MAX_RETRIES,
            retry_backoff_seconds=settings.CENSUS_GEOCODER_RETRY_BACKOFF_SECONDS,
        )
        self.stdout.write(summary.as_text())
