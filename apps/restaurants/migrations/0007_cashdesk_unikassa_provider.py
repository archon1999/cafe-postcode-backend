from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0005_canonical_cashdesk_fiscal_provider'),
        ('restaurants', '0006_restaurant_vat_settings'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cashdesk',
            name='fiscal_provider',
            field=models.CharField(
                choices=[('fiscal-drive-service', 'FiscalDriveService'), ('unikassa', 'Unikassa')],
                default='fiscal-drive-service',
                max_length=32,
            ),
        ),
    ]
