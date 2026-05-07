from django.db import migrations


CANONICAL_PROVIDER = 'fiscal-drive-service'
LEGACY_PROVIDERS = ('soliq-ofd',)


def forwards(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    IntegrationConfig.objects.filter(kind='fiscal', provider__in=LEGACY_PROVIDERS).update(provider=CANONICAL_PROVIDER)


def backwards(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    IntegrationConfig.objects.filter(kind='fiscal', provider=CANONICAL_PROVIDER).update(provider='soliq-ofd')


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0005_remove_integration_config_mode'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
