from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from route_planner.services.locationiq_geocode_runner import run_locationiq_geocode_job


class Command(BaseCommand):
    help = (
        "Geocode FuelStation rows using LocationIQ (OSM data, separate API key from ORS). "
        "Free tier allows more requests/day than public Nominatim — sign up at locationiq.com."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--delay-seconds", type=float, default=0.0)
        parser.add_argument("--max-api-requests", type=int, default=None)
        parser.add_argument("--single-query", action="store_true")

    def handle(self, *args, **options):
        api_key = (settings.LOCATIONIQ_API_KEY or "").strip()
        if not api_key:
            raise CommandError("Set LOCATIONIQ_API_KEY in .env (free at https://locationiq.com/).")

        summary = run_locationiq_geocode_job(
            api_key=api_key,
            base_url=settings.LOCATIONIQ_BASE_URL,
            timeout_seconds=float(settings.LOCATIONIQ_TIMEOUT_SECONDS),
            min_request_interval_seconds=float(settings.LOCATIONIQ_MIN_REQUEST_INTERVAL_SECONDS),
            force=options["force"],
            limit=options["limit"],
            dry_run=options["dry_run"],
            delay_seconds=options["delay_seconds"],
            max_api_requests=options["max_api_requests"],
            single_query_only=options["single_query"],
            db_batch_size=settings.GEOCODE_DB_BATCH_SIZE,
        )
        self.stdout.write(summary.as_text())
