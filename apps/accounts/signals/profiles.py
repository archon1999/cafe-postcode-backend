from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import (
    BusinessPartnerUserProfile,
    EmployeeCompensationProfile,
    EmployeeProfile,
    RestaurantUserProfile,
    User,
)


@receiver(post_save, sender=User)
def ensure_user_profiles(sender, instance: User, **kwargs):
    EmployeeProfile.objects.get_or_create(user=instance)
    EmployeeCompensationProfile.objects.get_or_create(user=instance)

    if instance.restaurant_id:
        restaurant_profile, created = RestaurantUserProfile.objects.get_or_create(
            user=instance,
            defaults={
                'restaurant_id': instance.restaurant_id,
                'pin_code': instance.pin_code,
                'primary_hall_id': instance.primary_hall_id,
                'hall_switch_permission': instance.hall_switch_permission,
            },
        )
        if not created:
            changed_fields = []
            if restaurant_profile.restaurant_id != instance.restaurant_id:
                restaurant_profile.restaurant_id = instance.restaurant_id
                changed_fields.append('restaurant')
            if instance.pin_code and restaurant_profile.pin_code != instance.pin_code:
                restaurant_profile.pin_code = instance.pin_code
                changed_fields.append('pin_code')
            if restaurant_profile.primary_hall_id != instance.primary_hall_id:
                restaurant_profile.primary_hall_id = instance.primary_hall_id
                changed_fields.append('primary_hall')
            if restaurant_profile.hall_switch_permission != instance.hall_switch_permission:
                restaurant_profile.hall_switch_permission = instance.hall_switch_permission
                changed_fields.append('hall_switch_permission')
            if changed_fields:
                restaurant_profile.save(update_fields=changed_fields)
        if instance.allowed_halls.exists():
            restaurant_profile.allowed_halls.set(instance.allowed_halls.all())

    if instance.business_partner_id:
        business_partner_profile, created = BusinessPartnerUserProfile.objects.get_or_create(
            user=instance,
            defaults={'business_partner_id': instance.business_partner_id},
        )
        if not created and business_partner_profile.business_partner_id != instance.business_partner_id:
            business_partner_profile.business_partner_id = instance.business_partner_id
            business_partner_profile.save(update_fields=['business_partner'])
