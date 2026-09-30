import os

# Defaults for local pytest / manage.py when .env is not loaded.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-local-runs-only")
os.environ.setdefault("POSTGRES_DB", "fuel_route")
os.environ.setdefault("POSTGRES_USER", "fuel_route")
os.environ.setdefault("POSTGRES_PASSWORD", "fuel_route")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
