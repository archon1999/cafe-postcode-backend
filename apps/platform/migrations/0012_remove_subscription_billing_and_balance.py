from django.db import migrations


EXPIRY_SCHEDULE_NAME = 'platform.expire_restaurant_entitlements'


def remove_expiry_schedule(apps, schema_editor):
    try:
        from django_q.models import Schedule

        Schedule.objects.filter(name=EXPIRY_SCHEDULE_NAME).delete()
    except Exception:
        # The schedule table may not exist in lightweight/test environments.
        return


class Migration(migrations.Migration):
    dependencies = [
        ('platform', '0011_add_expense_permissions_to_access'),
    ]

    operations = [
        migrations.RunPython(remove_expiry_schedule, migrations.RunPython.noop),
        migrations.RemoveField(model_name='tariff', name='monthly_price'),
        migrations.RemoveField(model_name='tariff', name='yearly_price'),
        migrations.RemoveField(model_name='restaurantentitlement', name='starts_on'),
        migrations.RemoveField(model_name='restaurantentitlement', name='expires_on'),
        migrations.RemoveField(model_name='restaurantentitlement', name='billing_period'),
        migrations.RemoveField(model_name='restaurantentitlement', name='monthly_price'),
        migrations.RemoveField(model_name='restaurantentitlement', name='yearly_price'),
        migrations.DeleteModel(name='RestaurantBalanceTransaction'),
    ]
