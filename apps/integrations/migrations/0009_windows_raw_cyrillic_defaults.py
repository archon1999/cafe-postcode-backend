from django.db import migrations


def set_cyrillic_printer_defaults(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    for config in IntegrationConfig.objects.filter(kind='printer', provider='windows-raw'):
        settings = dict(config.settings or {})
        if settings.get('encoding') in (None, '', 'cp437', 'ibm437'):
            settings['encoding'] = 'cp1251'
        settings.setdefault('code_page', 46)
        config.settings = settings
        config.save(update_fields=['settings', 'updated_at'])


def unset_cyrillic_printer_defaults(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    for config in IntegrationConfig.objects.filter(kind='printer', provider='windows-raw'):
        settings = dict(config.settings or {})
        if settings.get('encoding') == 'cp1251':
            settings['encoding'] = 'cp437'
        if settings.get('code_page') == 46:
            settings.pop('code_page', None)
        config.settings = settings
        config.save(update_fields=['settings', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0008_clear_local_agent_device_endpoints'),
    ]

    operations = [
        migrations.RunPython(set_cyrillic_printer_defaults, unset_cyrillic_printer_defaults),
    ]
