import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(key: str, default: str | None = None) -> str:
    value = os.environ.get(key, default)
    if value is None or value == "":
        if default is not None:
            return default
        raise ValueError(f"Required environment variable {key} is not set.")
    return value


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int | None = None) -> int:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        if default is not None:
            return default
        raise ValueError(f"Required environment variable {key} is not set.")
    return int(raw)


def _env_decimal(key: str, default: str | None = None) -> Decimal:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        if default is not None:
            return Decimal(default)
        raise ValueError(f"Required environment variable {key} is not set.")
    return Decimal(raw)


SECRET_KEY = _env("SECRET_KEY", "django-insecure-dev-only-change-in-production")
DEBUG = _env_bool("DEBUG", False)

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,web,0.0.0.0").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "route_planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": _env("POSTGRES_DB"),
        "USER": _env("POSTGRES_USER"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": _env("POSTGRES_HOST", "localhost"),
        "PORT": _env("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel Route Planner API",
    "DESCRIPTION": "Fuel-efficient route planning for U.S. driving routes.",
    "VERSION": "0.1.0",
}

# External routing (OpenRouteService / HeiGIT)
ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
ORS_BASE_URL = _env("ORS_BASE_URL", "https://api.heigit.org").rstrip("/")
ORS_CONNECT_TIMEOUT_SECONDS = _env_int("ORS_CONNECT_TIMEOUT_SECONDS", 5)
ORS_READ_TIMEOUT_SECONDS = _env_int("ORS_READ_TIMEOUT_SECONDS", 30)
ORS_GEOCODE_DELAY_SECONDS = float(os.environ.get("ORS_GEOCODE_DELAY_SECONDS", "0.15"))
ORS_GEOCODE_MAX_API_REQUESTS_PER_RUN = _env_int("ORS_GEOCODE_MAX_API_REQUESTS_PER_RUN", 2800)

NOMINATIM_USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "")
NOMINATIM_DELAY_SECONDS = float(os.environ.get("NOMINATIM_DELAY_SECONDS", "1.1"))
NOMINATIM_MIN_REQUEST_INTERVAL_SECONDS = float(
    os.environ.get("NOMINATIM_MIN_REQUEST_INTERVAL_SECONDS", "1.0")
)
NOMINATIM_TIMEOUT_SECONDS = _env_int("NOMINATIM_TIMEOUT_SECONDS", 30)
GEOCODE_DB_BATCH_SIZE = _env_int("GEOCODE_DB_BATCH_SIZE", 100)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuel-route-planner",
    }
}

# Application tuning (used by future route/fuel services)
ROUTE_CACHE_TIMEOUT_SECONDS = _env_int("ROUTE_CACHE_TIMEOUT_SECONDS", 86400)
ROUTE_STATION_CORRIDOR_MILES = _env_decimal("ROUTE_STATION_CORRIDOR_MILES", "5")
VEHICLE_MAX_RANGE_MILES = _env_int("VEHICLE_MAX_RANGE_MILES", 500)
VEHICLE_MPG = _env_int("VEHICLE_MPG", 10)

# U.S. Census batch geocoder (offline station preprocessing)
CENSUS_GEOCODER_BATCH_URL = _env(
    "CENSUS_GEOCODER_BATCH_URL",
    "https://geocoding.geo.census.gov/geocoder/locations/addressbatch",
)
CENSUS_GEOCODER_BENCHMARK = _env("CENSUS_GEOCODER_BENCHMARK", "Public_AR_Current")
CENSUS_GEOCODER_BATCH_SIZE = _env_int("CENSUS_GEOCODER_BATCH_SIZE", 1000)
CENSUS_GEOCODER_TIMEOUT_SECONDS = _env_int("CENSUS_GEOCODER_TIMEOUT_SECONDS", 60)
CENSUS_GEOCODER_MAX_RETRIES = _env_int("CENSUS_GEOCODER_MAX_RETRIES", 3)
CENSUS_GEOCODER_RETRY_BACKOFF_SECONDS = _env_int("CENSUS_GEOCODER_RETRY_BACKOFF_SECONDS", 2)
