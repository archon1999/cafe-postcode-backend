from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('devices', '0002_alter_devicepairing_status_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='legacy_migration_key',
            field=models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True),
        ),
    ]
