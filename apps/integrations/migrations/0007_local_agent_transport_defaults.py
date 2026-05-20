from django.db import migrations


LOCAL_AGENT_PROVIDERS = {
    'marta-softpos',
    'unikassa',
    'windows-raw',
}


def set_local_agent_transport(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    for config in IntegrationConfig.objects.filter(provider__in=LOCAL_AGENT_PROVIDERS).iterator():
        settings = dict(config.settings or {})
        settings.setdefault('transport', 'local-agent')
        config.settings = settings
        config.save(update_fields=['settings'])


def unset_local_agent_transport(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    for config in IntegrationConfig.objects.filter(provider__in=LOCAL_AGENT_PROVIDERS).iterator():
        settings = dict(config.settings or {})
        if settings.get('transport') == 'local-agent':
            settings.pop('transport', None)
            config.settings = settings
            config.save(update_fields=['settings'])


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0006_canonical_fiscal_drive_provider'),
    ]

    operations = [
        migrations.RunPython(set_local_agent_transport, unset_local_agent_transport),
    ]
