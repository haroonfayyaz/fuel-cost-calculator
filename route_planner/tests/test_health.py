import pytest
from django.conf import settings


def test_django_settings_load():
    assert settings.configured
    assert "route_planner" in settings.INSTALLED_APPS


def test_health_endpoint_returns_200(client):
    response = client.get("/api/health/")
    assert response.status_code == 200


def test_health_endpoint_returns_expected_json(client):
    response = client.get("/api/health/")
    assert response.json() == {"status": "ok"}
