from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import EmployeeProfile, User


@receiver(post_save, sender=User)
def ensure_user_profiles(sender, instance: User, **kwargs):
    if kwargs.get('raw'):
        return
    # Authentication metadata updates must not read/create employee profiles or
    # synchronize POS PINs. Dedicated analytics login has no such privileges.
    update_fields = kwargs.get('update_fields')
    if update_fields and set(update_fields) <= {'last_login', 'password'}:
        return

    EmployeeProfile.objects.get_or_create(user=instance)
    try:
        restaurant_profile = instance.restaurant_profile
    except ObjectDoesNotExist:
        restaurant_profile = None
    if restaurant_profile is not None and instance.pin_code and restaurant_profile.pin_code != instance.pin_code:
        restaurant_profile.pin_code = instance.pin_code
        restaurant_profile.save(update_fields=['pin_code'])
