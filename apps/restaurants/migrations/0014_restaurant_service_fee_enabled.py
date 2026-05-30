from django.db import migrations, models


def enable_existing_service_fee(apps, schema_editor):
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    Restaurant.objects.filter(service_fee_percent__gt=0).update(service_fee_enabled=True)


def disable_service_fee(apps, schema_editor):
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    Restaurant.objects.update(service_fee_enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0013_prepstation_printer_cooks'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='service_fee_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(enable_existing_service_fee, disable_service_fee),
    ]
