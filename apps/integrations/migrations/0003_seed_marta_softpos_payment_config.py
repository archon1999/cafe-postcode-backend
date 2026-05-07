from django.db import migrations


DEFAULT_MARTA_SETTINGS = {
    'endpoint_url': '',
    'timeout_seconds': 180,
    'tax_number': '',
    'amount_multiplier': 100,
    'hmac_secret': '',
    'seeded_by': 'marta_softpos_0003',
}


def seed_marta_softpos_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    Restaurant = apps.get_model('restaurants', 'Restaurant')

    for restaurant in Restaurant.objects.all():
        IntegrationConfig.objects.update_or_create(
            restaurant=restaurant,
            kind='payment',
            provider='marta-softpos',
            defaults={
                'mode': 'live',
                'is_enabled': False,
                'settings': DEFAULT_MARTA_SETTINGS,
            },
        )


def remove_seeded_marta_softpos_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    IntegrationConfig.objects.filter(
        kind='payment',
        provider='marta-softpos',
        settings__seeded_by='marta_softpos_0003',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(seed_marta_softpos_configs, remove_seeded_marta_softpos_configs),
    ]
