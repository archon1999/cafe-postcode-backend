from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.restaurants.models import Restaurant

from .services import ensure_restaurant_templates


@receiver(post_save, sender=Restaurant, dispatch_uid='printing.ensure_restaurant_templates')
def create_default_print_templates(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        ensure_restaurant_templates(restaurant=instance)
