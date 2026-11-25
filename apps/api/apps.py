from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.api"
    verbose_name = "Mobile sync API"

    def ready(self):
        # The signal handlers that keep change tracking in step
        from apps.api import tracking  # noqa: F401
