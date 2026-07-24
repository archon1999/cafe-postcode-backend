from django.db import migrations
from django.db.models import Q


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


def add_expense_permissions_to_access(apps, schema_editor):
    Permission = apps.get_model('users', 'Permission')
    Tariff = apps.get_model('platform', 'Tariff')
    RestaurantEntitlement = apps.get_model('platform', 'RestaurantEntitlement')

    pos_permissions = list(Permission.objects.filter(code__in=POS_EXPENSE_PERMISSION_CODES))
    admin_permissions = list(Permission.objects.filter(code__in=ADMIN_EXPENSE_PERMISSION_CODES))

    for tariff in Tariff.objects.filter(allowed_roles__code__in=MANAGER_ROLE_CODES).distinct():
        tariff.permissions.add(*pos_permissions)
    for tariff in Tariff.objects.filter(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES).distinct():
        tariff.permissions.add(*admin_permissions)

    manager_entitlements = RestaurantEntitlement.objects.filter(
        Q(allowed_roles__code__in=MANAGER_ROLE_CODES)
        | Q(restaurant__user_profiles__user__role__code__in=MANAGER_ROLE_CODES)
    ).distinct()
    for entitlement in manager_entitlements:
        entitlement.permissions.add(*pos_permissions)

    admin_entitlements = RestaurantEntitlement.objects.filter(
        Q(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES)
        | Q(restaurant__user_profiles__user__role__code__in=RESTAURANT_ADMIN_ROLE_CODES)
    ).distinct()
    for entitlement in admin_entitlements:
        entitlement.permissions.add(*admin_permissions)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('platform', '0010_add_modifier_permissions_to_admin_access'),
        ('users', '0002_authsession_surface_and_expiry'),
    ]

    operations = [
        migrations.RunPython(add_expense_permissions_to_access, noop_reverse),
    ]
