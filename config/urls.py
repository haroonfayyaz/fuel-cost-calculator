from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from route_planner.views_demo import FuelPlanDemoView

urlpatterns = [
    path("demo/fuel-plan/", FuelPlanDemoView.as_view(), name="fuel-plan-demo"),
    path("admin/", admin.site.urls),
    path("api/", include("route_planner.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
