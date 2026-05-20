from django.db import migrations


LOCAL_AGENT_DEVICE_PROVIDERS = {'marta-softpos', 'unikassa'}
def clear_local_agent_device_endpoints(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    for config in IntegrationConfig.objects.filter(provider__in=LOCAL_AGENT_DEVICE_PROVIDERS).iterator():
        settings = dict(config.settings or {})
        if settings.get('transport') != 'local-agent':
            continue

        settings['endpoint_url'] = ''
        settings.pop('endpointUrl', None)
        config.settings = settings
        config.save(update_fields=['settings'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0007_local_agent_transport_defaults'),
    ]

    operations = [
        migrations.RunPython(clear_local_agent_device_endpoints, noop_reverse),
    ]
