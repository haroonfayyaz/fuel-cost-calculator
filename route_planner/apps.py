from django.apps import AppConfig


class RoutePlannerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "route_planner"

    def ready(self) -> None:
        import route_planner.spectacular_extensions  # noqa: F401
