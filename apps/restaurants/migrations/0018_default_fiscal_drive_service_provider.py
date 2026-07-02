from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0017_restaurant_social'),
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
