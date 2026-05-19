from django.db import migrations


def assign_unikassa_fiscal_configs(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')

    restaurant_ids = CashDesk.objects.values_list('restaurant_id', flat=True).distinct()
    for restaurant_id in restaurant_ids:
        config = (
            IntegrationConfig.objects.filter(
                restaurant_id=restaurant_id,
                kind='fiscal',
                provider='unikassa',
                is_enabled=True,
            )
            .order_by('-created_at')
            .first()
        )
        if config is None:
            continue
        CashDesk.objects.filter(
            restaurant_id=restaurant_id,
            fiscal_integration__isnull=True,
        ).update(fiscal_integration_id=config.id)


def unassign_unikassa_fiscal_configs(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    CashDesk.objects.filter(fiscal_integration__provider='unikassa').update(fiscal_integration_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0010_use_unikassa_fiscal_provider'),
    ]

    operations = [
        migrations.RunPython(assign_unikassa_fiscal_configs, unassign_unikassa_fiscal_configs),
    ]
