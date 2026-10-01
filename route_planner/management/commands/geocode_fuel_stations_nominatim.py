from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from route_planner.services.nominatim_geocode_runner import run_nominatim_geocode_job


class Command(BaseCommand):
    help = (
        "Geocode FuelStation rows using OpenStreetMap Nominatim. "
        "Does not consume ORS/HeiGIT quota (use this to finish bulk geocoding in ~2 hours). "
        "See https://operations.osmfoundation.org/policies/nominatim/"
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--delay-seconds",
            type=float,
            default=None,
            help="Extra pause after each station (default NOMINATIM_DELAY_SECONDS). "
            "HTTP calls are already spaced by NOMINATIM_MIN_REQUEST_INTERVAL_SECONDS (1s).",
        )
        parser.add_argument(
            "--max-api-requests",
            type=int,
            default=None,
            help="Optional cap on Nominatim calls this run (default: no cap).",
        )
        parser.add_argument(
            "--single-query",
            action="store_true",
            help="Only try address+city+state (skip name fallback).",
        )

    def handle(self, *args, **options):
        user_agent = settings.NOMINATIM_USER_AGENT.strip()
        if not user_agent:
            raise CommandError(
                "Set NOMINATIM_USER_AGENT in .env (your app name and contact email)."
            )

        delay = options["delay_seconds"]
        if delay is None:
            delay = float(settings.NOMINATIM_DELAY_SECONDS)

        max_requests = options["max_api_requests"]

        summary = run_nominatim_geocode_job(
            user_agent=user_agent,
            timeout_seconds=float(settings.NOMINATIM_TIMEOUT_SECONDS),
            force=options["force"],
            limit=options["limit"],
            dry_run=options["dry_run"],
            delay_seconds=delay,
            max_api_requests=max_requests,
            single_query_only=options["single_query"],
            db_batch_size=settings.GEOCODE_DB_BATCH_SIZE,
            min_request_interval_seconds=float(settings.NOMINATIM_MIN_REQUEST_INTERVAL_SECONDS),
        )

        self.stdout.write(summary.as_text())
