from django.db.models import Q

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.users.models import Permission


POS_EXPENSE_PERMISSION_CODES = (
    'pos_cash_expenses.create',
    'pos_cash_expenses.void',
)
ADMIN_EXPENSE_PERMISSION_CODES = (
    'expense_categories.view',
    'expense_categories.create',
    'expense_categories.update',
    'expenses.view',
    'expenses.update',
)
MANAGER_ROLE_CODES = ('manager', 'fast_food_manager')
RESTAURANT_ADMIN_ROLE_CODES = ('restaurant_admin', 'fast_food_admin')


def grant_default_expense_access() -> None:
    pos_permissions = list(Permission.objects.filter(code__in=POS_EXPENSE_PERMISSION_CODES))
    admin_permissions = list(Permission.objects.filter(code__in=ADMIN_EXPENSE_PERMISSION_CODES))

    if pos_permissions:
        for tariff in Tariff.objects.filter(allowed_roles__code__in=MANAGER_ROLE_CODES).distinct():
            tariff.permissions.add(*pos_permissions)
        manager_entitlements = RestaurantEntitlement.objects.filter(
            Q(allowed_roles__code__in=MANAGER_ROLE_CODES)
            | Q(restaurant__user_profiles__user__role__code__in=MANAGER_ROLE_CODES)
        ).distinct()
        for entitlement in manager_entitlements:
            entitlement.permissions.add(*pos_permissions)

    if admin_permissions:
        for tariff in Tariff.objects.filter(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES).distinct():
            tariff.permissions.add(*admin_permissions)
        admin_entitlements = RestaurantEntitlement.objects.filter(
            Q(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES)
            | Q(restaurant__user_profiles__user__role__code__in=RESTAURANT_ADMIN_ROLE_CODES)
        ).distinct()
        for entitlement in admin_entitlements:
            entitlement.permissions.add(*admin_permissions)
