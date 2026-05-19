from django.db import migrations


FISCAL_SKIP_PERMISSION_CODE = 'pos_fiscal_receipts.skip'
CASHIER_ROLE_CODES = ('cashier', 'manager', 'fast_food_cashier', 'fast_food_manager')


def add_fiscal_skip_permission_to_cashier_tariffs(apps, schema_editor):
    Permission = apps.get_model('users', 'Permission')
    Tariff = apps.get_model('platform', 'Tariff')
    permission = Permission.objects.filter(code=FISCAL_SKIP_PERMISSION_CODE).first()
    if permission is None:
        return

    for tariff in Tariff.objects.filter(allowed_roles__code__in=CASHIER_ROLE_CODES).distinct():
        tariff.permissions.add(permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('platform', '0007_add_shift_permissions_to_tariffs'),
    ]

    operations = [
        migrations.RunPython(add_fiscal_skip_permission_to_cashier_tariffs, noop_reverse),
    ]
