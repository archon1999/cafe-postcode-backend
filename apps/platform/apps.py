from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'apps.platform'

    def ready(self):
        import apps.platform.signals  # noqa: F401
