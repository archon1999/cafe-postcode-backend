from django.apps import AppConfig


class TelegramReportsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.telegram_reports"

    def ready(self):
        import apps.telegram_reports.signals  # noqa: F401

