from django.db import migrations, models


CANONICAL_PROVIDER = 'fiscal-drive-service'
LEGACY_PROVIDERS = ('mock', 'soliq-ofd')


def forwards(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    CashDesk.objects.filter(fiscal_provider__in=LEGACY_PROVIDERS).update(fiscal_provider=CANONICAL_PROVIDER)


def backwards(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    CashDesk.objects.filter(fiscal_provider=CANONICAL_PROVIDER).update(fiscal_provider='soliq-ofd')


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0004_alter_cashdesk_fiscal_provider'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
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
