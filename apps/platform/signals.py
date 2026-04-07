from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.platform.services import ensure_expiry_schedule


@receiver(post_migrate)
def bootstrap_expiry_schedule(sender, app_config, **kwargs):
    if app_config.name != 'apps.platform':
        return

    ensure_expiry_schedule()
