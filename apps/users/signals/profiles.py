from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import EmployeeProfile, User


@receiver(post_save, sender=User)
def ensure_user_profiles(sender, instance: User, **kwargs):
    if kwargs.get('raw'):
        return

    EmployeeProfile.objects.get_or_create(user=instance)
    try:
        restaurant_profile = instance.restaurant_profile
    except ObjectDoesNotExist:
        restaurant_profile = None
    if restaurant_profile is not None and instance.pin_code and restaurant_profile.pin_code != instance.pin_code:
        restaurant_profile.pin_code = instance.pin_code
        restaurant_profile.save(update_fields=['pin_code'])
