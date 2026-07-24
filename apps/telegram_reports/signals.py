from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.telegram_reports.schedules import ensure_report_schedules


@receiver(post_migrate)
def bootstrap_telegram_report_schedules(sender, app_config, **kwargs):
    if app_config.name != "apps.telegram_reports":
        return
    ensure_report_schedules()

