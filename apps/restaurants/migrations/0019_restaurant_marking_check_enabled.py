from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0018_default_fiscal_drive_service_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='marking_check_enabled',
            field=models.BooleanField(default=False),
        ),
    ]
