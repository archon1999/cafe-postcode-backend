from django.db import migrations
from django.db.models import Q


PRINT_TEMPLATE_PERMISSION_CODES = (
    'print_templates.view',
    'print_templates.create',
    'print_templates.update',
)
RESTAURANT_ADMIN_ROLE_CODES = ('restaurant_admin', 'fast_food_admin')


def add_print_template_permissions_to_admin_access(apps, schema_editor):
    Permission = apps.get_model('users', 'Permission')
    Tariff = apps.get_model('platform', 'Tariff')
    RestaurantEntitlement = apps.get_model('platform', 'RestaurantEntitlement')

    permissions = list(Permission.objects.filter(code__in=PRINT_TEMPLATE_PERMISSION_CODES))
    if not permissions:
        return

    tariffs = Tariff.objects.filter(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES).distinct()
    for tariff in tariffs:
        tariff.permissions.add(*permissions)

    entitlements = RestaurantEntitlement.objects.filter(
        Q(allowed_roles__code__in=RESTAURANT_ADMIN_ROLE_CODES)
        | Q(restaurant__user_profiles__user__role__code__in=RESTAURANT_ADMIN_ROLE_CODES)
    ).distinct()
    for entitlement in entitlements:
        entitlement.permissions.add(*permissions)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('platform', '0008_add_fiscal_skip_permission_to_cashier_tariffs'),
        ('users', '0002_authsession_surface_and_expiry'),
    ]

    operations = [
        migrations.RunPython(add_print_template_permissions_to_admin_access, noop_reverse),
    ]
