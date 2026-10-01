# Fuel Route Planner

Django API that plans a U.S. driving route, finds fuel stations near the route corridor in PostGIS, and computes a refueling plan that minimizes fuel purchased en route.

## Architecture

Request flow:

```
Client
  -> Django API (DRF)
  -> Geocoder (ORS Pelias, endpoint text only)
  -> OpenRouteService Directions [1 call]
  -> PostGIS station corridor query (single SQL)
  -> Fuel optimizer (candidates only)
  -> Response
```

Fuel stations are **pre-geocoded offline** (Census batch, LocationIQ, Nominatim, or ORS management commands) and stored in PostgreSQL. A route request does **not** geocode thousands of station addresses and does **not** call the routing API per station. Only start/finish need geocoding when sent as text.

Cached geocode and route geometry reduce repeat traffic; fuel prices and stop selection are recomputed on each request from the local database.

## Tech stack

- Django
- Django REST Framework
- PostgreSQL / PostGIS
- OpenRouteService / HeiGIT (routing + optional geocoding)
- U.S. Census batch geocoder (offline station preprocessing)
- pytest

## Setup

### Environment variables

Copy the example file and set at least `SECRET_KEY`, `POSTGRES_PASSWORD`, and `ORS_API_KEY`:

```bash
cp .env.example .env
```

See `.env.example` for routing timeouts, cache TTLs, corridor width (`ROUTE_STATION_CORRIDOR_MILES`), vehicle constants, and optional `REDIS_URL`, `LOCATIONIQ_API_KEY`, `NOMINATIM_USER_AGENT`.

### Database and application

Docker Compose runs PostGIS and the web app (recommended):

```bash
docker compose up --build
```

The web container waits for the database, runs migrations, and serves on port **8000**.

Manual migration (if needed):

```bash
docker compose exec web python manage.py migrate
```

### CSV import

Import U.S. rows from the bundled dataset (non-U.S. and invalid prices are skipped; physical duplicates collapsed):

```bash
docker compose exec web python manage.py import_fuel_prices data/fuel-prices.csv
```

### Fuel station geocoding

Stations must have `geocoding_status=matched` and a `location` point to appear in corridor search. Pick one bulk path (not required for every row to match):

```bash
# U.S. Census batch (fast, lower match rate on highway exits)
docker compose exec web python manage.py geocode_fuel_stations

# LocationIQ (good bulk throughput; set LOCATIONIQ_API_KEY in .env)
docker compose exec web python manage.py geocode_fuel_stations_locationiq

# Public Nominatim (slow; set NOMINATIM_USER_AGENT)
docker compose exec web python manage.py geocode_fuel_stations_nominatim

# ORS/Pelias (shares ORS daily quota with routing)
docker compose exec web python manage.py geocode_fuel_stations_ors
```

Long `/fuel-plan/` trips need enough **matched** stations within the route corridor (default 5 miles). Short trips under 500 miles may succeed with zero fuel stops.

## Commands

```bash
# Start stack
docker compose up --build

# Import fuel CSV
docker compose exec web python manage.py import_fuel_prices data/fuel-prices.csv

# Geocode (example)
docker compose exec web python manage.py geocode_fuel_stations_locationiq

# Migrations
docker compose exec web python manage.py migrate

# Tests
docker compose exec web pytest

# Optional: OpenAPI
# http://localhost:8000/api/docs/
# http://localhost:8000/api/schema/
```

## API

`POST /api/v1/routes/fuel-plan/`

Each endpoint is either a **non-empty location string** or an object with `latitude` and `longitude`.

**Text locations:**

```json
{
  "start": "Dallas, TX",
  "finish": "Houston, TX"
}
```

**Coordinates:**

```json
{
  "start": { "latitude": 32.7767, "longitude": -96.7970 },
  "finish": { "latitude": 29.7604, "longitude": -95.3698 }
}
```

**Example response (shape):**

```json
{
  "route": {
    "type": "LineString",
    "coordinates": [[-96.797, 32.7767], [-95.3698, 29.7604]]
  },
  "distance_miles": 242.5,
  "duration_seconds": 14500.0,
  "vehicle": {
    "mpg": 10,
    "maximum_range_miles": 500,
    "tank_capacity_gallons": "50"
  },
  "fuel_stops": [],
  "fuel_consumed_gallons": "24.25",
  "fuel_purchased_gallons": "0",
  "total_fuel_cost": "0",
  "assumptions": {
    "starts_with_full_tank": true,
    "starting_fuel_cost_included": false
  }
}
```

When refueling is required, `fuel_stops` includes station metadata, `route_mile`, `price_per_gallon`, `gallons_purchased`, and `fuel_cost`.

```bash
curl -s -X POST http://localhost:8000/api/v1/routes/fuel-plan/ \
  -H "Content-Type: application/json" \
  -d '{"start":"Dallas, TX","finish":"Houston, TX"}'
```

Health: `GET /api/health/`

## Fuel assumptions

- 500-mile maximum range on a full tank
- 10 MPG
- 50-gallon tank capacity (500 ÷ 10)
- Trip starts with a full tank
- Initial fuel already in the tank is **not** included in `total_fuel_cost` (only en-route purchases)

Configurable via `VEHICLE_MAX_RANGE_MILES` and `VEHICLE_MPG` in `.env`.

## Optimization algorithm

The route is treated as a one-dimensional line (mile markers from the driving distance). Candidate stations are ordered by position along the route.

Greedy refueling at each decision point:

1. If current fuel can reach the destination, stop buying fuel.
2. If a cheaper station is reachable ahead, buy the **minimum** gallons needed to reach the nearest cheaper stop (respecting tank capacity).
3. Otherwise buy the minimum needed to continue (either enough to reach the destination or a full-tank top-up, whichever is less).
4. After a fill when no cheaper stop is reachable, advance to the farthest reachable candidate before repeating.

All gallon and dollar math uses `Decimal`. Same-mile duplicates keep the lowest price.

## External API calls

Per **fuel-plan** request (uncached):

| Input | Calls |
|-------|--------|
| Coordinates only | **1** directions request |
| Text start and finish | **2** geocoding + **1** directions |
| Identical repeat request | **0** (geocode + route geometry served from Django cache when populated) |

No directions or geocoding calls are made **per fuel station**. Station coordinates come from the database.

Offline bulk geocoding commands are separate and rate-limited; they are not part of a single route request.

## Correctness

Tests live under `route_planner/tests/`:

- **Boundary / optimizer** — 499 / 500 / 501 mile routes, tank limits, Decimal costs, destination behavior, randomized invariant checks (`test_fuel_optimizer.py`)
- **PostGIS** — corridor inclusion/exclusion, ordering, single-query station search (`test_station_finder.py`)
- **Mocked provider** — ORS geocode/route HTTP status mapping, lon/lat order, cache keys, timeouts (`test_open_route_service.py`)
- **Integration** — API status codes, orchestration, cache call counts, performance query shape (`test_api.py`, `test_route_planner.py`, `test_performance.py`)
- **CSV import** — U.S./Canada filtering, bad prices, idempotency, duplicates (`test_import_fuel_prices.py`)

All automated tests mock external HTTP; no live ORS calls in pytest.

## Limitations

- Stations are filtered to a **configurable corridor** around the route polyline (`ROUTE_STATION_CORRIDOR_MILES`, default 5). Stops far from the driven path are excluded.
- The app does **not** compute separate driveway or per-station highway detours; that would require many additional routing API calls.
- Station coordinates depend on geocoder quality (Census often weak on interstate exits; LocationIQ/Nominatim/ORS are alternatives).
- Fuel prices come from the imported CSV snapshot, not live rack or pump prices.
- Very long routes return **422** if the optimizer cannot refuel within range given corridor candidates.

## Running tests

```bash
docker compose exec web pytest
```

With coverage (install `pytest-cov` in the container if not in the image yet):

```bash
docker compose exec web sh -c 'pip install pytest-cov -q && pytest route_planner/tests/ --cov=route_planner --cov-report=term -q'
```

## Demo map

Manual verification UI (Leaflet, not a production frontend):

http://localhost:8000/demo/fuel-plan/

Submit start/finish text; the page calls `POST /api/v1/routes/fuel-plan/` and draws the returned route and fuel stop markers. Default example uses a short Texas route that succeeds without refueling; longer trips require sufficient geocoded corridor stations.
