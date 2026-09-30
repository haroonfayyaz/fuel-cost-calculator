# Fuel Route Planner

API for fuel-efficient U.S. driving routes: ORS routing, PostGIS station corridor search, and greedy fuel-cost optimization.

## Prerequisites

- Docker and Docker Compose
- Python 3.12 (optional, for local development outside Docker)
- HeiGIT / OpenRouteService API key (`ORS_API_KEY`)

## Setup

1. Copy the example environment file and set values (especially `SECRET_KEY`, `POSTGRES_PASSWORD`, and `ORS_API_KEY`):

   ```bash
   cp .env.example .env
   ```

2. Build and start services:

   ```bash
   docker compose up --build
   ```

   The web container waits for PostgreSQL to become healthy, then runs migrations before starting Django.

## Data pipeline (fuel prices are not replaced)

1. **Import prices** from the bundled CSV (creates/updates `FuelStation` rows; prices and addresses stay as in the file):

   ```bash
   docker compose exec web python manage.py import_fuel_prices
   ```

2. **Geocode stations** so they appear along routes.

   **Option A — finish in one sitting (recommended, no ORS quota):** OpenStreetMap Nominatim (~1 request/sec → ~2–3 hours for ~6k rows). Set a real contact in `.env`:

   ```bash
   # In .env:
   # NOMINATIM_USER_AGENT=FuelRoutePlanner/0.1 (you@example.com)

   docker compose exec web python manage.py geocode_fuel_stations_nominatim --dry-run
   docker compose exec web python manage.py geocode_fuel_stations_nominatim
   ```

   Expect **~3–4 hours** for ~6k rows (1.1s pause per station plus 1–2 Nominatim calls each). Progress lines print every 25 stations on stderr. Monitor with a second terminal:

   ```bash
   docker compose exec web python manage.py geocode_fuel_stations_nominatim --dry-run
   ```

   Use ORS only for **routing** (`/fuel-plan/`) while Nominatim fills station coordinates.

   **Option B — ORS/Pelias (same key as routing, ~3000 requests/day on free tier):**

   ```bash
   docker compose exec web python manage.py geocode_fuel_stations_ors --dry-run
   docker compose exec web python manage.py geocode_fuel_stations_ors
   # Stops after 2800 calls/run; repeat daily. Set ORS_GEOCODE_MAX_API_REQUESTS_PER_RUN=0 only if you have a paid quota.
   ```

   **Option C — Census batch (free, unlimited batches, low match rate on highway addresses):**

   ```bash
   docker compose exec web python manage.py geocode_fuel_stations --limit 1000
   ```

   Typical workflow: Census optional → **Nominatim for bulk** → ORS for live route API only. Re-run Nominatim until `--dry-run` shows `Eligible: 0`.

3. **Plan a route** via API (see below).

## Migrations

```bash
docker compose exec web python manage.py migrate
```

## Tests

```bash
docker compose exec web pytest
```

Docker is the recommended environment (PostGIS/GDAL).

## API

- OpenAPI schema: http://localhost:8000/api/schema/
- Swagger UI: http://localhost:8000/api/docs/
- Health: `GET /api/health/`

### Fuel plan

`POST /api/v1/routes/fuel-plan/`

Text endpoints:

```json
{
  "start": "Dallas, TX",
  "finish": "Los Angeles, CA"
}
```

Coordinates:

```json
{
  "start": { "latitude": 32.7767, "longitude": -96.7970 },
  "finish": { "latitude": 34.0522, "longitude": -118.2437 }
}
```

Example:

```bash
curl -s -X POST http://localhost:8000/api/v1/routes/fuel-plan/ \
  -H "Content-Type: application/json" \
  -d '{"start":"Dallas, TX","finish":"Houston, TX"}' | jq .
```

Long routes return **422** if not enough geocoded stations exist within the route corridor (default 5 miles). Short trips under the 500-mile tank range may succeed with zero fuel stops.

## Environment tuning

| Variable | Purpose |
|----------|---------|
| `ORS_API_KEY` | Routing and station geocoding |
| `ROUTE_STATION_CORRIDOR_MILES` | Search radius around route polyline |
| `ORS_GEOCODE_DELAY_SECONDS` | Pause between geocoding API calls |
| `ORS_GEOCODE_MAX_API_REQUESTS_PER_RUN` | Stop geocode run before exhausting daily ORS quota (default 2800) |
| `VEHICLE_MAX_RANGE_MILES` / `VEHICLE_MPG` | Tank model for optimization |
