from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0020_remove_unikassa_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='pos_monitor_variant',
            field=models.CharField(
                choices=[('default', 'Default'), ('light_compact', 'Light Compact')],
                default='default',
                max_length=32,
            ),
        ),
    ]
