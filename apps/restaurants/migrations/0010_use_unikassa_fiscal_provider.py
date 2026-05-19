from django.db import migrations, models


OLD_ENDPOINT_URLS = {'', 'http://127.0.0.1:3449', 'http://localhost:3449'}
UNIKASSA_ENDPOINT_URL = 'http://127.0.0.1:8181/api/v1'


def _normalize_settings(settings):
    normalized = dict(settings or {})
    endpoint_url = str(normalized.get('endpoint_url') or normalized.get('endpointUrl') or '').strip()
    if endpoint_url in OLD_ENDPOINT_URLS:
        normalized['endpoint_url'] = UNIKASSA_ENDPOINT_URL
    return normalized


def _merge_settings(target_settings, source_settings):
    merged = dict(target_settings or {})
    for key, value in (source_settings or {}).items():
        if key not in merged or merged[key] in (None, ''):
            merged[key] = value
    return _normalize_settings(merged)


def migrate_fiscal_drive_to_unikassa(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')

    for source in IntegrationConfig.objects.filter(kind='fiscal', provider='fiscal-drive-service').order_by('id'):
        source.settings = _normalize_settings(source.settings)
        target = (
            IntegrationConfig.objects.filter(
                restaurant_id=source.restaurant_id,
                kind='fiscal',
                provider='unikassa',
            )
            .exclude(id=source.id)
            .order_by('-is_enabled', '-created_at')
            .first()
        )

        if target is not None:
            target.settings = _merge_settings(target.settings, source.settings)
            target.is_enabled = target.is_enabled or source.is_enabled
            target.save(update_fields=('settings', 'is_enabled', 'updated_at'))
            CashDesk.objects.filter(fiscal_integration_id=source.id).update(fiscal_integration_id=target.id)
            source.delete()
            continue

        source.provider = 'unikassa'
        source.save(update_fields=('provider', 'settings', 'updated_at'))

    CashDesk.objects.filter(fiscal_provider='fiscal-drive-service').update(fiscal_provider='unikassa')


def reverse_unikassa_to_fiscal_drive(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')

    IntegrationConfig.objects.filter(kind='fiscal', provider='unikassa').update(provider='fiscal-drive-service')
    CashDesk.objects.filter(fiscal_provider='unikassa').update(fiscal_provider='fiscal-drive-service')


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0009_cashdesk_payment_integration'),
    ]

    operations = [
        migrations.RunPython(migrate_fiscal_drive_to_unikassa, reverse_unikassa_to_fiscal_drive),
        migrations.AlterField(
            model_name='cashdesk',
            name='fiscal_provider',
            field=models.CharField(
                choices=[('unikassa', 'Unikassa')],
                default='unikassa',
                max_length=32,
            ),
        ),
    ]
