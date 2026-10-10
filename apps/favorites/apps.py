from django.apps import AppConfig


class FavoritesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.favorites"

    def ready(self):
        from apps.favorites import signals  # noqa: F401
