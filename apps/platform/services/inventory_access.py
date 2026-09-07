"""Give existing restaurant administrators access to the new inventory module."""

from django.db.models import Q

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.users.models import Permission


INVENTORY_PERMISSION_CODES = (
    'admin.inventory.view', 'admin.inventory.manage', 'admin.inventory.post',
    'admin.inventory.view_cost', 'admin.inventory.analyze',
)
ADMIN_ROLE_CODES = ('restaurant_admin', 'fast_food_admin')


def grant_default_inventory_access():
    permissions = list(Permission.objects.filter(code__in=INVENTORY_PERMISSION_CODES))
    if not permissions:
        return
    for tariff in Tariff.objects.filter(allowed_roles__code__in=ADMIN_ROLE_CODES).distinct():
        tariff.permissions.add(*permissions)
    entitlements = RestaurantEntitlement.objects.filter(
        Q(allowed_roles__code__in=ADMIN_ROLE_CODES)
        | Q(restaurant__user_profiles__user__role__code__in=ADMIN_ROLE_CODES)
    ).distinct()
    for entitlement in entitlements:
        entitlement.permissions.add(*permissions)
