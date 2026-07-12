from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.restaurants.models import DistributionPoint, Restaurant


@receiver(post_save, sender=Restaurant, dispatch_uid='restaurants.ensure_delivery_distribution_point')
def ensure_delivery_distribution_point(sender, instance, created, **kwargs):
    if created:
        DistributionPoint.objects.get_or_create(
            restaurant=instance,
            kind=DistributionPoint.Kind.DELIVERY,
            defaults={'name': 'Delivery', 'is_active': True},
        )
