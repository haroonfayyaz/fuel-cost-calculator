# Fuel Route Planner

Bootstrap API for fuel-efficient U.S. route planning (routing and fuel optimization not implemented yet).

## Prerequisites

- Docker and Docker Compose
- Python 3.12 (optional, for local development outside Docker)

## Setup

1. Copy the example environment file and set values (especially `SECRET_KEY` and `POSTGRES_PASSWORD`):

   ```bash
   cp .env.example .env
   ```

2. Build and start services:

   ```bash
   docker compose up --build
   ```

   The web container waits for PostgreSQL to become healthy, then runs migrations before starting Django.

   Application code is bind-mounted into the container (`.:/app`), so Python changes reload automatically with `runserver`. Rebuild only when `Dockerfile` or `requirements.txt` change:

   ```bash
   docker compose up --build
   ```

## Migrations

Migrations run automatically on container start. To run them manually:

```bash
docker compose exec web python manage.py migrate
```

## Tests

With services running:

```bash
docker compose exec web pytest
```

For a local virtualenv, GeoDjango requires GDAL/GEOS on the host. **Docker is the recommended way** to run checks and tests.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY and POSTGRES_PASSWORD
export $(grep -v '^#' .env | xargs)
pytest
```

## API documentation

- OpenAPI schema: http://localhost:8000/api/schema/
- Swagger UI: http://localhost:8000/api/docs/

## Health check

```bash
curl http://localhost:8000/api/health/
```

Expected response: `{"status":"ok"}`
