"""Manual verification UI for the fuel-plan API (demo only)."""

from django.urls import reverse
from django.views.generic import TemplateView


class FuelPlanDemoView(TemplateView):
    template_name = "route_planner/fuel_plan_demo.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fuel_plan_api_path"] = reverse("fuel-plan")
        return context
