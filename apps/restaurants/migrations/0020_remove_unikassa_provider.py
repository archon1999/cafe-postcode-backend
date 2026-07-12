from django.db import migrations, models


def migrate_unikassa_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    DistributionPoint = apps.get_model('restaurants', 'DistributionPoint')
    Restaurant = apps.get_model('restaurants', 'Restaurant')

    for config in IntegrationConfig.objects.filter(kind='fiscal', provider='unikassa').select_related('restaurant'):
        settings = dict(config.settings or {})
        settings['tax_number'] = settings.get('tax_number') or config.restaurant.tax_number
        for key in ('fiscal', 'Fiscal', 'endpoint_url', 'endpointUrl'):
            settings.pop(key, None)
        settings['transport'] = 'local-agent'
        config.provider = 'fiscal-drive-service'
        config.settings = settings
        config.save(update_fields=('provider', 'settings', 'updated_at'))

    CashDesk.objects.filter(fiscal_provider='unikassa').update(fiscal_provider='fiscal-drive-service')
    for restaurant_id in Restaurant.objects.values_list('id', flat=True).iterator():
        DistributionPoint.objects.get_or_create(
            restaurant_id=restaurant_id,
            kind='delivery',
            defaults={'name': 'Delivery', 'is_active': True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0011_integrationconfig_name'),
        ('restaurants', '0019_restaurant_marking_check_enabled'),
    ]

    operations = [
        migrations.RunPython(migrate_unikassa_configs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='cashdesk',
            name='fiscal_provider',
            field=models.CharField(
                choices=[('fiscal-drive-service', 'FiscalDriveService')],
                default='fiscal-drive-service',
                max_length=32,
            ),
        ),
    ]
