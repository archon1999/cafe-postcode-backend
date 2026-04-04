from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='restaurantentitlement',
            name='operational_settings',
        ),
        migrations.RemoveField(
            model_name='tariff',
            name='classification',
        ),
        migrations.RemoveField(
            model_name='tariff',
            name='operational_settings',
        ),
    ]
