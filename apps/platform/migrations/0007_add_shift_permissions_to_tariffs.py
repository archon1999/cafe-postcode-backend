from django.db import migrations


SHIFT_PERMISSION_CODES = ('pos_cash_shift.manage', 'pos_fiscal_shift.manage')


def add_shift_permissions_to_manager_tariffs(apps, schema_editor):
    Permission = apps.get_model('users', 'Permission')
    Tariff = apps.get_model('platform', 'Tariff')

    shift_permissions = list(Permission.objects.filter(code__in=SHIFT_PERMISSION_CODES))
    if not shift_permissions:
        return

    for tariff in Tariff.objects.filter(allowed_roles__code__in=('manager', 'fast_food_manager')).distinct():
        tariff.permissions.add(*shift_permissions)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('platform', '0006_businesspartner_extra_permissions'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_shift_permissions_to_manager_tariffs, noop_reverse),
    ]
