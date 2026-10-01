"""Smoke tests for the manual fuel-plan demo page."""

from django.urls import reverse


def test_fuel_plan_demo_page_loads(client):
    url = reverse("fuel-plan-demo")
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()
    assert "Demo / manual verification UI" in content
    assert reverse("fuel-plan") in content
    assert "leaflet" in content.lower()
    assert "openstreetmap" in content.lower()
