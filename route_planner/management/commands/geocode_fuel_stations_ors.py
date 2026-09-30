from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from route_planner.services.ors_geocode_runner import run_ors_geocode_job
from route_planner.services.routing.base import RoutingAuthenticationError
from route_planner.services.routing.factory import get_routing_provider


class Command(BaseCommand):
    help = (
        "Geocode existing FuelStation rows using Pelias/ORS (same provider as route planning). "
        "Does not modify fuel prices or re-import the CSV. "
        "Respect your daily ORS quota with --max-api-requests."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of stations to attempt in this run.",
        )
        parser.add_argument(
            "--max-api-requests",
            type=int,
            default=None,
            help=(
                "Stop after this many Pelias geocode API calls "
                f"(default: ORS_GEOCODE_MAX_API_REQUESTS_PER_RUN={settings.ORS_GEOCODE_MAX_API_REQUESTS_PER_RUN}). "
                "Use ~2800 on a 3000/day quota to leave room for route planning."
            ),
        )
        parser.add_argument(
            "--single-query",
            action="store_true",
            help="Only try address+city+state (skip name fallback) to halve worst-case API usage.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-geocode stations even when a location is already stored.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count eligible stations without calling the geocoding API.",
        )
        parser.add_argument(
            "--delay-seconds",
            type=float,
            default=None,
            help="Pause between stations (defaults to ORS_GEOCODE_DELAY_SECONDS).",
        )

    def handle(self, *args, **options):
        delay = options["delay_seconds"]
        if delay is None:
            delay = float(settings.ORS_GEOCODE_DELAY_SECONDS)

        max_api_requests = options["max_api_requests"]
        if max_api_requests is None:
            max_api_requests = settings.ORS_GEOCODE_MAX_API_REQUESTS_PER_RUN
        if max_api_requests == 0:
            max_api_requests = None

        try:
            provider = get_routing_provider()
        except RoutingAuthenticationError as exc:
            raise CommandError("ORS_API_KEY is not configured.") from exc

        summary = run_ors_geocode_job(
            provider,
            force=options["force"],
            limit=options["limit"],
            dry_run=options["dry_run"],
            delay_seconds=delay,
            max_api_requests=max_api_requests,
            single_query_only=options["single_query"],
            db_batch_size=settings.GEOCODE_DB_BATCH_SIZE,
        )

        self.stdout.write(summary.as_text())
