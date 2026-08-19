from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'apps.devices'

    def ready(self):
        import apps.devices.signals  # noqa: F401
