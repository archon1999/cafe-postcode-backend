"""Make staff capabilities available to tariffs that include the matching roles."""

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.users.models import Permission


WORKFORCE_MANAGER_ROLES = ('restaurant_admin', 'fast_food_admin', 'manager', 'fast_food_manager')
STAFF_FINANCE_ROLES = ('restaurant_admin', 'fast_food_admin')
WORKFORCE_CODES = ('workforce.view', 'workforce.schedule', 'workforce.approve')
ADMIN_WORKFORCE_CODES = ('workforce.config',)
STAFF_FINANCE_CODES = ('staff.payroll.view', 'staff.payroll.manage', 'staff.payroll.payout')


def grant_default_staff_access():
    grants = (
        (WORKFORCE_MANAGER_ROLES, WORKFORCE_CODES),
        (STAFF_FINANCE_ROLES, ADMIN_WORKFORCE_CODES + STAFF_FINANCE_CODES),
    )
    for role_codes, permission_codes in grants:
        permissions = list(Permission.objects.filter(code__in=permission_codes))
        if not permissions:
            continue
        for tariff in Tariff.objects.filter(allowed_roles__code__in=role_codes).distinct():
            tariff.permissions.add(*permissions)
        for entitlement in RestaurantEntitlement.objects.filter(allowed_roles__code__in=role_codes).distinct():
            entitlement.permissions.add(*permissions)
