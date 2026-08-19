from django.utils import timezone

def deactivate_restaurant_access(*, restaurant, entitlement=None, deactivated_at=None) -> None:
    timestamp = deactivated_at or timezone.now()
    target_entitlement = entitlement if entitlement is not None else getattr(restaurant, 'entitlement', None)

    restaurant.is_active = False
    restaurant.deactivated_at = timestamp
    restaurant.save(update_fields=['is_active', 'deactivated_at', 'updated_at'])

    if target_entitlement is not None and target_entitlement.is_active:
        target_entitlement.is_active = False
        target_entitlement.save(update_fields=['is_active', 'updated_at'])
