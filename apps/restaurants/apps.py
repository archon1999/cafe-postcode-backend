from django.apps import AppConfig


class RestaurantsConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'apps.restaurants'

    def ready(self):
        from . import signals  # noqa: F401
