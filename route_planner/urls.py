from django.urls import path

from route_planner.views import HealthCheckView
from route_planner.views_fuel_plan import FuelPlanView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("v1/routes/fuel-plan/", FuelPlanView.as_view(), name="fuel-plan"),
]
