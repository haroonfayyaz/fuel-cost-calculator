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

   | Method | Speed | Cost | Command |
   |--------|--------|------|---------|
   | **LocationIQ** (recommended) | ~2 req/s, 5k+/day free tier | Free signup | `geocode_fuel_stations_locationiq` |
   | Public Nominatim | ~1 req/s, strict limits | Free | `geocode_fuel_stations_nominatim` |
   | ORS/Pelias | 2800/run, 3k/day shared with routing | Your ORS key | `geocode_fuel_stations_ors` |
   | U.S. Census batch | Very fast batches | Free, low match on exits | `geocode_fuel_stations` |

   **Option A — LocationIQ (fastest practical bulk path):**

   1. Create a free key at [locationiq.com](https://locationiq.com/).
   2. Add to `.env`: `LOCATIONIQ_API_KEY=pk....`
   3. `docker compose up -d web`
   4. ```bash
      docker compose exec web python manage.py geocode_fuel_stations_locationiq --dry-run
      docker compose exec web python manage.py geocode_fuel_stations_locationiq --single-query
      ```
      `--single-query` skips the name fallback (half the API calls; slightly fewer matches).

   **Option B — Public Nominatim (slow, no signup):** set `NOMINATIM_USER_AGENT`, then `geocode_fuel_stations_nominatim` (~3–4 hours for ~6k rows).

   **Option C — ORS only:** `geocode_fuel_stations_ors` — save your 3000/day quota for routing if possible.

   **Option D — Census:** `geocode_fuel_stations` — quick but most highway addresses stay unmatched.

   You do **not** need 100% geocoded rows for the app to work — long routes need enough **matched** stations along the corridor. Try `/fuel-plan/` after LocationIQ; re-run until `--dry-run` eligible is low.

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
