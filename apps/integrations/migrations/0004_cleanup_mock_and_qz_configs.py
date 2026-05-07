from django.db import migrations


REMOVED_PROVIDERS = ('mock-fiscal', 'mock-payment', 'mock-printer', 'qz-tray')


def remove_mock_and_qz_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    IntegrationConfig.objects.filter(provider__in=REMOVED_PROVIDERS).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0003_seed_marta_softpos_payment_config'),
    ]

    operations = [
        migrations.RunPython(remove_mock_and_qz_configs, noop),
    ]
