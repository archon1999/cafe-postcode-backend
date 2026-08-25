from django.db import migrations


SHIFT_VIEW_PERMISSION_CODE = 'pos_cash_shift.view'
MANAGER_ROLE_CODES = ('manager', 'fast_food_manager')


def add_cash_shift_view_permission_to_manager_tariffs(apps, schema_editor):
    Permission = apps.get_model('users', 'Permission')
    Tariff = apps.get_model('platform', 'Tariff')

    permission = Permission.objects.filter(code=SHIFT_VIEW_PERMISSION_CODE).first()
    if permission is None:
        return

    for tariff in Tariff.objects.filter(allowed_roles__code__in=MANAGER_ROLE_CODES).distinct():
        tariff.permissions.add(permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('platform', '0012_remove_subscription_billing_and_balance'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_cash_shift_view_permission_to_manager_tariffs, noop_reverse),
    ]
