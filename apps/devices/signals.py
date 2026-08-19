from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.devices.maintenance import ensure_security_maintenance_schedule


@receiver(post_migrate)
def bootstrap_security_maintenance_schedule(sender, app_config, **kwargs):
    if app_config.name != 'apps.devices':
        return
    ensure_security_maintenance_schedule()
