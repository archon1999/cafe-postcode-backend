from django.db.models import Q

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.users.models import Permission


MODIFIER_PERMISSION_CODES = (
    'catalog_modifier_groups.view',
    'catalog_modifier_groups.create',
    'catalog_modifier_groups.update',
    'catalog_modifier_groups.delete',
)
RESTAURANT_ADMIN_ROLE_CODES = ('restaurant_admin', 'fast_food_admin')


def grant_default_modifier_access() -> None:
    permissions = list(Permission.objects.filter(code__in=MODIFIER_PERMISSION_CODES))
    if not permissions:
        return

    for tariff in Tariff.objects.filter(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES).distinct():
        tariff.permissions.add(*permissions)

    entitlements = RestaurantEntitlement.objects.filter(
        Q(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES)
        | Q(restaurant__user_profiles__user__role__code__in=RESTAURANT_ADMIN_ROLE_CODES)
    ).distinct()
    for entitlement in entitlements:
        entitlement.permissions.add(*permissions)
